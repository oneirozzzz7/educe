"""
器官 B: 语言偏好检测 — P2 正交性验证

检测用户偏好的编程语言，达到阈值后注入"优先使用X语言"。
与 verbosity 完全正交（语言 vs 长度无关）。

设计（Opus 4.8 确认）：
- 只看用户输入（不分析 AI 回复，避免反馈环）
- 显式信号："用 Python" / "改成 TypeScript"
- 隐式信号：用户消息中的代码块语言标记 ```python
- 统计分布，主导语言超过阈值后注入
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

log = logging.getLogger("educe.organ_codelang")

# ═══ 信号检测 ═══

EXPLICIT_LANG_PATTERNS = re.compile(
    r'(?:用|使用|改成|换成|write in|use|switch to)\s*'
    r'(python|typescript|javascript|java|go|rust|c\+\+|ruby|php|swift|kotlin|scala|shell|bash)',
    re.IGNORECASE
)

FENCED_CODE_LANG = re.compile(r'```(python|typescript|javascript|java|go|rust|cpp|ruby|php|swift|kotlin|scala|bash|sh)\b', re.IGNORECASE)

LANG_NORMALIZE = {
    "js": "javascript", "ts": "typescript", "py": "python",
    "cpp": "c++", "sh": "bash", "shell": "bash",
}

CONFIDENCE_THRESHOLD = 0.70
OBSERVE_PER_SIGNAL = 0.20


def normalize_lang(lang: str) -> str:
    return LANG_NORMALIZE.get(lang.lower(), lang.lower())


# ═══ CodeLangOrgan ═══

@dataclass
class LangState:
    counts: Counter = field(default_factory=Counter)
    total: int = 0
    crystallized_lang: str | None = None
    state: str = "idle"

    def dominant(self) -> tuple[str, float] | None:
        if not self.counts or self.total == 0:
            return None
        lang, count = self.counts.most_common(1)[0]
        return (lang, count / self.total)


class CodeLangOrgan:
    """器官 B: 语言偏好"""

    name = "code_lang"

    def __init__(self):
        self._state = LangState()

    def observe(self, user_input: str, ai_reply_len: int = 0) -> None:
        explicit = EXPLICIT_LANG_PATTERNS.search(user_input)
        if explicit:
            lang = normalize_lang(explicit.group(1))
            self._state.counts[lang] += 2
            self._state.total += 2
            if self._state.state == "idle":
                self._state.state = "observing"

        fenced = FENCED_CODE_LANG.findall(user_input)
        for lang in fenced:
            self._state.counts[normalize_lang(lang)] += 1
            self._state.total += 1
            if self._state.state == "idle":
                self._state.state = "observing"

    async def check(self) -> None:
        if self._state.state == "crystallized":
            return

        dom = self._state.dominant()
        if dom and dom[1] >= CONFIDENCE_THRESHOLD and self._state.total >= 3:
            self._state.crystallized_lang = dom[0]
            self._state.state = "crystallized"
            log.info("CodeLangOrgan crystallized: %s (%.0f%%)", dom[0], dom[1] * 100)

    def inject(self) -> str | None:
        if self._state.state == "crystallized" and self._state.crystallized_lang:
            return f"用户偏好使用 {self._state.crystallized_lang} 语言。代码示例优先使用 {self._state.crystallized_lang}，除非用户指定其他语言。"
        return None

    def status(self) -> dict:
        dom = self._state.dominant()
        confidence = dom[1] if dom else 0
        return {
            "id": "code_lang",
            "name": self.name,
            "family": "code_lang",
            "state": self._state.state,
            "confidence": round(confidence, 3),
            "observe_count": self._state.total,
            "confirm_count": 1 if self._state.state == "crystallized" else 0,
            "hint": self.inject(),
            "detail": dict(self._state.counts.most_common(5)) if self._state.counts else {},
        }

    async def revert(self) -> None:
        self._state = LangState()
