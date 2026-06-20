"""
Organ Registry — 多器官统一管理

设计原则（Opus 4.8 讨论确认）：
- Organ Protocol: observe / state / inject / revert
- OrganRegistry: observe_all / collect_injections / list_status
- 注入策略：简单拼接（不仲裁），P3 再加冲突检测
- 每个器官独立学习、独立注入、独立撤销
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

log = logging.getLogger("educe.organ_registry")


@runtime_checkable
class Organ(Protocol):
    """器官统一接口"""
    name: str

    def observe(self, user_input: str, ai_reply_len: int = 0) -> None:
        """热路径：记录观察信号"""
        ...

    async def check(self) -> None:
        """冷路径：检测信号并推进状态机"""
        ...

    def inject(self) -> str | None:
        """返回 system prompt 注入片段，或 None"""
        ...

    def status(self) -> dict:
        """返回当前状态（供 Status 面板）"""
        ...

    async def revert(self) -> None:
        """撤销/重置器官状态"""
        ...


class OrganRegistry:
    """多器官注册表"""

    def __init__(self):
        self._organs: dict[str, Organ] = {}

    def register(self, organ: Organ) -> None:
        self._organs[organ.name] = organ

    def get(self, name: str) -> Organ | None:
        return self._organs.get(name)

    def observe_all(self, user_input: str, ai_reply_len: int = 0) -> None:
        """热路径：所有器官同时观察"""
        for organ in self._organs.values():
            try:
                organ.observe(user_input, ai_reply_len)
            except Exception as e:
                log.debug("organ %s observe error: %s", organ.name, e)

    async def check_all(self) -> None:
        """冷路径：所有器官检测信号"""
        for organ in self._organs.values():
            try:
                await organ.check()
            except Exception as e:
                log.debug("organ %s check error: %s", organ.name, e)

    def collect_injections(self) -> str:
        """收集所有器官的注入片段，简单拼接"""
        parts = []
        for organ in self._organs.values():
            try:
                hint = organ.inject()
                if hint:
                    parts.append(hint)
            except Exception:
                pass
        return "\n".join(parts) if parts else ""

    def list_status(self) -> list[dict]:
        """返回所有器官状态"""
        result = []
        for organ in self._organs.values():
            try:
                result.append(organ.status())
            except Exception:
                pass
        return result

    async def revert_organ(self, name: str) -> bool:
        """撤销指定器官"""
        organ = self._organs.get(name)
        if organ:
            await organ.revert()
            return True
        return False
