"""
Educe Unified Tool Registry
统一工具注册 — 让框架可以连接万物

所有外部能力（Skill、MCP、API、脚本）都是 Tool：
- 有名字、描述、参数定义
- 模型通过 <action type="use_tool" name="xxx"> 调用
- 框架根据 tool.type 路由到对应执行器

支持的工具类型：
- builtin: 框架内置能力（代码审查、数据分析等）
- script: 本地脚本（python/node/bash）
- api: HTTP API 调用
- mcp: MCP 协议工具服务器（TODO）
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable
import logging

log = logging.getLogger("educe.core.tool_registry")


@dataclass
class ToolDef:
    name: str
    description: str
    type: str = "builtin"  # builtin | script | api | mcp
    params_schema: dict = field(default_factory=dict)
    # For script type
    command: str = ""
    # For api type
    url: str = ""
    method: str = "POST"
    headers: dict = field(default_factory=dict)
    # For builtin type
    handler: Callable[..., Awaitable[str]] | None = None


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self._register_builtins()

    def register(self, tool: ToolDef):
        self._tools[tool.name] = tool

    def unregister(self, name: str):
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def get_descriptions(self) -> str:
        if not self._tools:
            return "（无可用工具）"
        lines = []
        for t in self._tools.values():
            params_hint = ""
            if t.params_schema:
                params_hint = f" 参数: {json.dumps(t.params_schema, ensure_ascii=False)}"
            lines.append(f"- {t.name}: {t.description}{params_hint}")
        return "\n".join(lines)

    async def execute(self, name: str, params: str) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"success": False, "output": f"工具 '{name}' 未注册。可用工具：{', '.join(self._tools.keys()) or '无'}"}

        try:
            if tool.type == "builtin" and tool.handler:
                result = await tool.handler(params)
                return {"success": True, "output": result}

            elif tool.type == "script":
                return await self._exec_script(tool, params)

            elif tool.type == "api":
                return await self._exec_api(tool, params)

            elif tool.type == "mcp":
                return {"success": False, "output": "MCP 工具暂未实现"}

            else:
                return {"success": False, "output": f"未知工具类型: {tool.type}"}
        except Exception as e:
            return {"success": False, "output": f"工具执行失败: {str(e)[:200]}"}

    async def _exec_script(self, tool: ToolDef, params: str) -> dict:
        cmd = tool.command.replace("{params}", params)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            output = result.stdout + (("\n[stderr]\n" + result.stderr) if result.stderr else "")
            return {"success": result.returncode == 0, "output": output[:3000]}
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "脚本执行超时 (30s)"}

    async def _exec_api(self, tool: ToolDef, params: str) -> dict:
        import httpx
        try:
            params_dict = json.loads(params) if params.strip().startswith("{") else {"input": params}
        except (ValueError, TypeError):
            params_dict = {"input": params}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if tool.method.upper() == "GET":
                    resp = await client.get(tool.url, params=params_dict, headers=tool.headers)
                else:
                    resp = await client.post(tool.url, json=params_dict, headers=tool.headers)
                return {"success": resp.status_code < 400, "output": resp.text[:3000]}
        except Exception as e:
            return {"success": False, "output": f"API 调用失败: {e}"}

    def _register_builtins(self):
        self.register(ToolDef(
            name="code_review",
            description="对代码进行质量审查，给出改进建议",
            type="builtin",
            handler=self._builtin_code_review,
        ))
        self.register(ToolDef(
            name="summarize",
            description="对长文本进行摘要总结",
            type="builtin",
            handler=self._builtin_summarize,
        ))
        self.register(ToolDef(
            name="web_search",
            description="搜索网络信息（模拟）",
            type="builtin",
            handler=self._builtin_web_search,
        ))

    async def _builtin_code_review(self, params: str) -> str:
        return f"[代码审查] 请提供代码文件路径或代码内容。收到的参数: {params[:100]}"

    async def _builtin_summarize(self, params: str) -> str:
        text = params[:2000]
        words = len(text)
        return f"[摘要] 输入 {words} 字符，需要模型处理。内容前 200 字: {text[:200]}..."

    async def _builtin_web_search(self, params: str) -> str:
        return f"[搜索] 关键词: {params}（网络搜索功能需要接入搜索 API）"

    # ═══ 从配置文件加载用户自定义工具 ═══

    def load_from_config(self, config_path: Path):
        if not config_path.exists():
            return
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            tools = data if isinstance(data, list) else data.get("tools", [])
            for t in tools:
                self.register(ToolDef(
                    name=t["name"],
                    description=t.get("description", ""),
                    type=t.get("type", "api"),
                    command=t.get("command", ""),
                    url=t.get("url", ""),
                    method=t.get("method", "POST"),
                    headers=t.get("headers", {}),
                    params_schema=t.get("params_schema", {}),
                ))
        except Exception as e:
            log.debug("suppressed: %s", e)
