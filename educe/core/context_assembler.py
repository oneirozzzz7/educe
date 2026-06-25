"""ContextAssembler — 按需召回相关资产注入模型上下文。

框架不判断，只提供信息。模型看到相关资产后自己决策。
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("educe.context_assembler")


class ContextAssembler:
    """根据当前意图从 AssetStore 召回相关资产，渲染为模型可读的 context 块。"""

    def __init__(self, store):
        self._store = store

    def assemble(self, user_input: str, action_type: str = "", top_k: int = 5) -> str:
        """召回与当前输入相关的资产，渲染为注入文本。

        返回空字符串表示无相关资产（不注入）。
        """
        query = f"{user_input} {action_type}".strip()
        entries = self._store.query_relevant(query, top_k=top_k)
        if not entries:
            return ""

        type_labels = {
            "precedent": "先例",
            "boundary": "边界",
            "fact": "知识",
            "convention": "偏好",
            "scar": "教训",
        }

        lines = []
        for e in entries:
            label = type_labels.get(e.type, e.type)
            lines.append(f"  [{label}] {e.content}")

        return "<context>\n" + "\n".join(lines) + "\n</context>"
