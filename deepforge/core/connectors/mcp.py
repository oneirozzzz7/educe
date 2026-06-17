"""
MCP Connector — 连接 MCP (Model Context Protocol) 服务器

支持 stdio 传输：启动子进程，通过 stdin/stdout 通信。
MCP server 的 tools 天然就是 Capabilities。

P0 健壮性保障：
- invoke 超时兜底（不会 hang）
- 子进程崩溃检测 + 自动重连
- 错误给用户友好提示
- 危险能力标记（write/delete 类）
- 调用日志

配置格式 (.educe/mcp.json):
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "description": "读写本地文件系统",
      "dangerous_capabilities": ["write_file", "edit_file", "move_file"]
    }
  ]
}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from deepforge.core.connector import Connector, Capability

log = logging.getLogger("deepforge.mcp")

# 默认的危险能力关键词（模糊匹配）
DANGEROUS_KEYWORDS = {"write", "delete", "remove", "move", "create", "edit", "append"}

INVOKE_TIMEOUT = 30  # 单次调用超时
CONNECT_TIMEOUT = 15  # 连接超时
MAX_RECONNECT_ATTEMPTS = 2


class MCPConnector(Connector):
    """MCP 协议连接器 — stdio 传输，含完整生命周期管理"""

    def __init__(self, name: str, summary: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, dangerous_capabilities: list[str] | None = None):
        self.name = name
        self.summary = summary
        self._command = command
        self._args = args or []
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._capabilities: list[Capability] = []
        self._dangerous_set: set[str] = set(dangerous_capabilities or [])
        self._initialized = False
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._connect_attempts = 0
        self._last_invoke_time = 0.0
        self._invoke_count = 0
        self._invoke_errors = 0

    @property
    def dangerous_capabilities(self) -> set[str]:
        """获取危险能力列表（显式配置 + 关键词匹配）"""
        result = set(self._dangerous_set)
        for cap in self._capabilities:
            cap_lower = cap.name.lower()
            if any(kw in cap_lower for kw in DANGEROUS_KEYWORDS):
                result.add(cap.name)
        return result

    def is_dangerous(self, capability: str) -> bool:
        """判断某个能力是否需要用户确认"""
        if capability in self._dangerous_set:
            return True
        cap_lower = capability.lower()
        return any(kw in cap_lower for kw in DANGEROUS_KEYWORDS)

    async def _ensure_connected(self) -> bool:
        """确保 MCP server 进程在运行并已初始化"""
        if self._initialized and self._process and self._process.returncode is None:
            return True

        async with self._lock:
            # double check
            if self._initialized and self._process and self._process.returncode is None:
                return True

            # 子进程已崩溃：清理后重连
            if self._process and self._process.returncode is not None:
                log.warning("MCP %s: process died (rc=%d), reconnecting...",
                            self.name, self._process.returncode)
                self._initialized = False
                self._process = None

            if self._connect_attempts >= MAX_RECONNECT_ATTEMPTS:
                log.error("MCP %s: max reconnect attempts reached", self.name)
                return False

            self._connect_attempts += 1
            success = await self._connect()
            if success:
                self._connect_attempts = 0  # 成功后重置
            return success

    async def _connect(self) -> bool:
        """启动 MCP server 子进程并完成握手"""
        try:
            self._process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    self._command, *self._args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=self._env,
                ),
                timeout=CONNECT_TIMEOUT,
            )
            log.info("MCP %s started (pid=%d)", self.name, self._process.pid)

            # MCP 初始化握手
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "educe", "version": "0.1.0"},
            })

            if not init_result:
                log.error("MCP %s: initialize handshake failed", self.name)
                await self._kill_process()
                return False

            await self._send_notification("notifications/initialized", {})

            # 获取工具列表
            tools_result = await self._send_request("tools/list", {})
            if tools_result and "tools" in tools_result:
                self._capabilities = [
                    Capability(
                        name=t["name"],
                        description=t.get("description", ""),
                        params_schema=t.get("inputSchema", {}),
                    )
                    for t in tools_result["tools"]
                ]
                log.info("MCP %s: discovered %d tools (%d dangerous)",
                         self.name, len(self._capabilities), len(self.dangerous_capabilities))

            self._initialized = True
            return True

        except asyncio.TimeoutError:
            log.error("MCP %s: connection timeout (%ds)", self.name, CONNECT_TIMEOUT)
            await self._kill_process()
            return False
        except FileNotFoundError:
            log.error("MCP %s: command not found: %s", self.name, self._command)
            return False
        except Exception as e:
            log.error("MCP %s: connection failed: %s", self.name, str(e)[:100])
            await self._kill_process()
            return False

    async def _kill_process(self):
        """强制终止子进程"""
        if self._process:
            try:
                self._process.kill()
                await asyncio.wait_for(self._process.wait(), timeout=3)
            except Exception:
                pass
            self._process = None
        self._initialized = False

    async def _send_request(self, method: str, params: dict) -> dict | None:
        """发送 JSON-RPC request 并等待 response"""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            msg = json.dumps(request) + "\n"
            self._process.stdin.write(msg.encode())
            await self._process.stdin.drain()

            response_line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=INVOKE_TIMEOUT
            )

            if not response_line:
                log.warning("MCP %s: empty response for %s (process may have died)", self.name, method)
                return None

            response = json.loads(response_line.decode().strip())
            if "error" in response:
                err = response["error"]
                log.warning("MCP %s RPC error on %s: %s", self.name, method, err)
                return None

            return response.get("result", {})

        except asyncio.TimeoutError:
            log.error("MCP %s: request timeout (%ds) for %s", self.name, INVOKE_TIMEOUT, method)
            return None
        except (BrokenPipeError, ConnectionResetError):
            log.error("MCP %s: pipe broken during %s, process likely crashed", self.name, method)
            self._initialized = False
            return None
        except Exception as e:
            log.error("MCP %s: request failed for %s: %s", self.name, method, str(e)[:100])
            return None

    async def _send_notification(self, method: str, params: dict) -> None:
        """发送 JSON-RPC notification"""
        if not self._process or not self._process.stdin:
            return
        try:
            msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
            self._process.stdin.write(msg.encode())
            await self._process.stdin.drain()
        except Exception:
            pass

    async def capabilities(self) -> list[Capability]:
        """获取 MCP server 提供的所有工具"""
        if not self._initialized:
            await self._ensure_connected()
        return self._capabilities

    async def invoke(self, capability: str, params: dict) -> dict:
        """调用 MCP server 的某个工具，含超时兜底和错误处理"""
        self._invoke_count += 1
        self._last_invoke_time = time.time()

        if not await self._ensure_connected():
            self._invoke_errors += 1
            return {
                "success": False,
                "output": f"MCP 连接器 '{self.name}' 无法连接。请检查配置或稍后重试。",
            }

        log.info("MCP %s: invoking %s with %s", self.name, capability, str(params)[:100])

        result = await self._send_request("tools/call", {
            "name": capability,
            "arguments": params,
        })

        if result is None:
            self._invoke_errors += 1
            # 检查进程是否还活着
            if self._process and self._process.returncode is not None:
                return {
                    "success": False,
                    "output": f"MCP 连接器 '{self.name}' 进程已崩溃，下次调用将自动重连。",
                }
            return {
                "success": False,
                "output": f"MCP 工具 '{self.name}.{capability}' 调用超时或失败。",
            }

        # 解析 MCP tools/call 响应
        content_parts = result.get("content", [])
        output_parts = []
        for part in content_parts:
            if part.get("type") == "text":
                output_parts.append(part.get("text", ""))
            elif part.get("type") == "resource":
                output_parts.append(f"[resource: {part.get('uri', '')}]")

        output = "\n".join(output_parts) if output_parts else str(result)
        is_error = result.get("isError", False)

        if is_error:
            self._invoke_errors += 1

        return {"success": not is_error, "output": output[:3000]}

    async def health(self) -> bool:
        """连接器健康状态"""
        if not self._process:
            return False
        return self._process.returncode is None

    def stats(self) -> dict:
        """连接器统计信息"""
        return {
            "name": self.name,
            "connected": self._initialized and (self._process is not None and self._process.returncode is None),
            "capabilities_count": len(self._capabilities),
            "invoke_count": self._invoke_count,
            "invoke_errors": self._invoke_errors,
            "dangerous_count": len(self.dangerous_capabilities),
        }

    async def shutdown(self) -> None:
        """终止 MCP server 进程"""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()
            log.info("MCP %s shutdown (invokes=%d, errors=%d)",
                     self.name, self._invoke_count, self._invoke_errors)
        self._initialized = False
        self._process = None


def load_mcp_connectors(config_path: Path) -> list[MCPConnector]:
    """从配置文件加载 MCP 连接器列表"""
    if not config_path.exists():
        return []

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        servers = data.get("servers", [])
        connectors = []

        for server in servers:
            name = server.get("name", "")
            if not name:
                continue
            if not server.get("command"):
                log.warning("MCP config: server '%s' missing command, skipped", name)
                continue
            connectors.append(MCPConnector(
                name=name,
                summary=server.get("description", f"MCP: {name}"),
                command=server.get("command", ""),
                args=server.get("args", []),
                env=server.get("env"),
                dangerous_capabilities=server.get("dangerous_capabilities"),
            ))

        return connectors
    except json.JSONDecodeError as e:
        log.error("MCP config parse error in %s: %s", config_path, e)
        return []
    except Exception as e:
        log.error("Failed to load MCP config from %s: %s", config_path, e)
        return []
