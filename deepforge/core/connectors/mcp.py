"""
MCP Connector — 连接 MCP (Model Context Protocol) 服务器

支持 stdio 传输：启动子进程，通过 stdin/stdout 通信。
MCP server 的 tools 天然就是 Capabilities。

配置格式 (.deepforge/mcp.json):
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "description": "读写本地文件系统"
    }
  ]
}
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from deepforge.core.connector import Connector, Capability

log = logging.getLogger("deepforge.mcp")


class MCPConnector(Connector):
    """MCP 协议连接器 — stdio 传输"""

    def __init__(self, name: str, summary: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None):
        self.name = name
        self.summary = summary
        self._command = command
        self._args = args or []
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._capabilities: list[Capability] = []
        self._initialized = False
        self._request_id = 0
        self._lock = asyncio.Lock()

    async def _ensure_connected(self) -> bool:
        """确保 MCP server 进程在运行并已初始化"""
        if self._initialized and self._process and self._process.returncode is None:
            return True

        async with self._lock:
            if self._initialized and self._process and self._process.returncode is None:
                return True
            return await self._connect()

    async def _connect(self) -> bool:
        """启动 MCP server 子进程并完成握手"""
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._command, *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
            log.info("MCP server %s started (pid=%d)", self.name, self._process.pid)

            # MCP 初始化握手
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "educe", "version": "0.1.0"},
            })

            if not init_result:
                log.error("MCP %s: initialize failed", self.name)
                return False

            # 发送 initialized 通知
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
                log.info("MCP %s: discovered %d tools", self.name, len(self._capabilities))

            self._initialized = True
            return True

        except FileNotFoundError:
            log.error("MCP %s: command not found: %s", self.name, self._command)
            return False
        except Exception as e:
            log.error("MCP %s: connection failed: %s", self.name, str(e)[:100])
            return False

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

            # 读取响应（简化：假设一行一个 JSON-RPC 消息）
            response_line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=30
            )

            if not response_line:
                return None

            response = json.loads(response_line.decode().strip())
            if "error" in response:
                log.warning("MCP %s RPC error: %s", self.name, response["error"])
                return None

            return response.get("result", {})

        except asyncio.TimeoutError:
            log.error("MCP %s: request timeout for %s", self.name, method)
            return None
        except Exception as e:
            log.error("MCP %s: request failed: %s", self.name, str(e)[:100])
            return None

    async def _send_notification(self, method: str, params: dict) -> None:
        """发送 JSON-RPC notification（无 id，不期望响应）"""
        if not self._process or not self._process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            msg = json.dumps(notification) + "\n"
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
        """调用 MCP server 的某个工具"""
        if not await self._ensure_connected():
            return {"success": False, "output": f"MCP server '{self.name}' 连接失败"}

        result = await self._send_request("tools/call", {
            "name": capability,
            "arguments": params,
        })

        if result is None:
            return {"success": False, "output": f"MCP 工具 '{capability}' 调用失败"}

        # MCP tools/call 返回 content 数组
        content_parts = result.get("content", [])
        output_parts = []
        for part in content_parts:
            if part.get("type") == "text":
                output_parts.append(part.get("text", ""))
            elif part.get("type") == "resource":
                output_parts.append(f"[resource: {part.get('uri', '')}]")

        output = "\n".join(output_parts) if output_parts else str(result)
        is_error = result.get("isError", False)

        return {"success": not is_error, "output": output[:3000]}

    async def health(self) -> bool:
        if not self._process:
            return False
        return self._process.returncode is None

    async def shutdown(self) -> None:
        """终止 MCP server 进程"""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()
            log.info("MCP server %s shutdown", self.name)
        self._initialized = False


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
            connectors.append(MCPConnector(
                name=name,
                summary=server.get("description", f"MCP: {name}"),
                command=server.get("command", ""),
                args=server.get("args", []),
                env=server.get("env"),
            ))

        return connectors
    except Exception as e:
        log.error("Failed to load MCP config from %s: %s", config_path, e)
        return []
