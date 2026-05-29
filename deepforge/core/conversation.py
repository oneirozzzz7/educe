"""
DeepForge 对话管理器
服务端维护对话历史，按 token 预算注入 LLM，文件上下文智能保留

设计原则：
- 服务端维护，不依赖前端传历史
- token 预算控制，不撑爆 context window
- 文件上下文有黏性——追问自动保留，换话题自动清除
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


CONTINUE_PATTERNS = re.compile(
    r"这个|这篇|这段|这里|上面|上文|刚才|前面|你说的|你提到|"
    r"继续|接着|详细|展开|深入|更多|举例|为什么这样|怎么理解|"
    r"那么|所以|也就是说|换句话说|具体来说"
)


@dataclass
class Turn:
    role: str
    content: str
    timestamp: float = 0
    has_file: bool = False
    domain: str = ""


class ConversationManager:
    """对话历史管理——token 预算控制 + 文件上下文黏性"""

    def __init__(self, max_turns: int = 30, history_char_budget: int = 6000,
                 knowledge=None):
        self.turns: list[Turn] = []
        self.max_turns = max_turns
        self.history_char_budget = history_char_budget
        self.file_context: str = ""
        self._last_file_turn: int = -1
        self._knowledge = knowledge

    def add_user(self, content: str, file_content: str | None = None):
        """记录用户消息"""
        has_file = bool(file_content)
        if file_content:
            self.file_context = file_content
            self._last_file_turn = len(self.turns)

        self.turns.append(Turn(
            role="user", content=content,
            timestamp=time.time(), has_file=has_file,
        ))

        if len(self.turns) > self.max_turns * 2:
            self._distill_before_compact()
            self.turns = self.turns[-self.max_turns:]

    def add_assistant(self, content: str, domain: str = ""):
        """记录助手回复"""
        self.turns.append(Turn(
            role="assistant", content=content[:2000],
            timestamp=time.time(), domain=domain,
        ))

    def get_history_for_llm(self, token_budget: int | None = None) -> list[dict]:
        """从最近的 turn 往前，在预算内尽可能多地包含历史

        不包含最新一条 user 消息（那个由调用方单独传入）
        """
        budget = token_budget or self.history_char_budget

        if len(self.turns) < 2:
            return []

        history_turns = self.turns[:-1]

        result = []
        char_count = 0
        for turn in reversed(history_turns):
            turn_chars = len(turn.content)
            if char_count + turn_chars > budget:
                break
            result.insert(0, {"role": turn.role, "content": turn.content})
            char_count += turn_chars

        return result

    def get_active_file_context(self, current_input: str) -> str:
        """判断是否应该保留文件上下文

        规则：
        - 有文件上下文 + 最近3轮内上传过 + 当前消息有续问信号 → 保留
        - 否则 → 清除
        """
        if not self.file_context:
            return ""

        turns_since_file = len(self.turns) - self._last_file_turn
        if turns_since_file > 6:
            self.file_context = ""
            return ""

        if turns_since_file <= 2:
            return self.file_context

        if CONTINUE_PATTERNS.search(current_input):
            return self.file_context

        self.file_context = ""
        return ""

    def clear(self):
        """清空对话历史"""
        self.turns.clear()
        self.file_context = ""
        self._last_file_turn = -1

    def _distill_before_compact(self):
        """主动蒸馏——在裁剪前提取有价值的上下文到知识库"""
        if not self._knowledge:
            return
        try:
            from deepforge.core.knowledge_distiller import KnowledgeDistiller
            distiller = KnowledgeDistiller(self._knowledge)

            turns_to_drop = self.turns[:self.max_turns]
            for turn in turns_to_drop:
                if turn.role == "assistant" and len(turn.content) > 100:
                    domain = turn.domain or "general"
                    distiller.distill("", turn.content, domain)
        except Exception:
            pass
