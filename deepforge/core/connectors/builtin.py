"""
Builtin Connector — 包装现有 ToolRegistry 的 builtin/script/api 工具

向后兼容层：让旧的 ToolDef 继续工作，同时融入新的 Connector 体系。
"""
from __future__ import annotations

from deepforge.core.connector import Connector, Capability
from deepforge.core.tool_registry import ToolRegistry, ToolDef


class BuiltinConnector(Connector):
    """包装框架内置工具为 Connector"""

    name = "tools"
    summary = "框架内置工具和用户自定义工具"

    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    async def capabilities(self) -> list[Capability]:
        return [
            Capability(
                name=t.name,
                description=t.description,
                params_schema=t.params_schema,
            )
            for t in self._registry.list_all()
        ]

    async def invoke(self, capability: str, params: dict) -> dict:
        import json
        params_str = json.dumps(params, ensure_ascii=False) if isinstance(params, dict) else str(params)
        return await self._registry.execute(capability, params_str)

    async def health(self) -> bool:
        return True
