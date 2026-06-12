"""
Educe Connector System — 连接万物

分层架构：
- Connector: 一个"外部世界"（filesystem, github, mcp-server）
- Capability: 世界里的一个动作（read_file, create_issue）

两级描述（对弱模型最关键）：
- Level 1（常驻 prompt）：一行概要 "- github: 操作GitHub仓库"
- Level 2（按需注入）：模型选择后才展开详细 capability

向后兼容：use_tool action 继续工作，底层路由到 connector.invoke()
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("deepforge.connector")


@dataclass
class Capability:
    """一个 Connector 提供的具体能力"""
    name: str
    description: str
    params_schema: dict = field(default_factory=dict)


class Connector(ABC):
    """连接器基类 — 连接到一个外部世界"""

    name: str
    summary: str  # Level 1: 一行描述，常驻 system prompt

    @abstractmethod
    async def capabilities(self) -> list[Capability]:
        """Level 2: 详细能力列表（按需获取）"""
        ...

    @abstractmethod
    async def invoke(self, capability: str, params: dict) -> dict:
        """执行某个能力，返回 {"success": bool, "output": str}"""
        ...

    async def health(self) -> bool:
        """连接器是否可用"""
        return True

    async def shutdown(self) -> None:
        """清理资源"""
        pass


class ConnectorRegistry:
    """连接器注册表 — 管理所有 connector 的发现、描述、路由"""

    def __init__(self):
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.name] = connector
        log.info("Registered connector: %s", connector.name)

    def unregister(self, name: str) -> None:
        self._connectors.pop(name, None)

    def get(self, name: str) -> Connector | None:
        return self._connectors.get(name)

    def list_all(self) -> list[Connector]:
        return list(self._connectors.values())

    def get_level1_descriptions(self) -> str:
        """Level 1: 精简清单，常驻 system prompt"""
        if not self._connectors:
            return ""
        lines = [f"- {c.name}: {c.summary}" for c in self._connectors.values()]
        return "\n".join(lines)

    async def get_level2_description(self, connector_name: str) -> str:
        """Level 2: 某个 connector 的详细能力（按需）"""
        connector = self._connectors.get(connector_name)
        if not connector:
            return f"连接器 '{connector_name}' 不存在。"
        caps = await connector.capabilities()
        if not caps:
            return f"{connector.name}: 暂无可用能力。"
        lines = [f"[{connector.name}] {connector.summary}"]
        for cap in caps:
            params_hint = ""
            if cap.params_schema:
                import json
                params_hint = f" 参数: {json.dumps(cap.params_schema, ensure_ascii=False)}"
            lines.append(f"  - {cap.name}: {cap.description}{params_hint}")
        return "\n".join(lines)

    async def invoke(self, tool_name: str, params: str) -> dict:
        """路由调用 — 支持 "connector.capability" 或 "capability" 两种格式"""
        import json as _json

        # 解析 params
        try:
            params_dict = _json.loads(params) if params.strip().startswith("{") else {"input": params}
        except (ValueError, TypeError):
            params_dict = {"input": params}

        # 路由：如果 tool_name 包含 "."，则 "connector.capability" 格式
        if "." in tool_name:
            connector_name, capability_name = tool_name.split(".", 1)
        else:
            # 查找哪个 connector 拥有这个 capability
            connector_name, capability_name = await self._find_capability(tool_name)

        connector = self._connectors.get(connector_name)
        if not connector:
            available = ", ".join(self._connectors.keys()) or "无"
            return {"success": False, "output": f"连接器 '{connector_name}' 不存在。可用: {available}"}

        try:
            return await connector.invoke(capability_name, params_dict)
        except Exception as e:
            log.error("Connector %s.%s invoke failed: %s", connector_name, capability_name, e)
            return {"success": False, "output": f"调用失败: {str(e)[:200]}"}

    async def _find_capability(self, capability_name: str) -> tuple[str, str]:
        """在所有 connector 中查找 capability"""
        for name, connector in self._connectors.items():
            caps = await connector.capabilities()
            for cap in caps:
                if cap.name == capability_name:
                    return name, capability_name
        return "", capability_name

    async def shutdown_all(self) -> None:
        """关闭所有 connector"""
        for connector in self._connectors.values():
            try:
                await connector.shutdown()
            except Exception as e:
                log.warning("Shutdown %s failed: %s", connector.name, e)
