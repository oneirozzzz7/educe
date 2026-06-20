"""
器官 A: Verbosity 双向检测 — P1 核心

检测用户偏好简短回答还是详细回答，
达到 confidence 阈值后 PROPOSE，用户确认后 CRYSTALLIZE。

设计（Opus 4.8 讨论确认）：
- 信号检测在冷路径（异步），不阻塞主回路
- ring buffer 存 turn_meta，worker 定期消费
- confidence_state.json 持久化
- 双向互相抵消
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable

from educe.core.evolution_bus import (
    EvolutionBus, EvolutionEvent, EvolutionKind, OrganRef, EventBuilder,
    OBSERVE_GAIN, CONFIRM_JUMP, REVERT_DROP, HOT_THRESHOLD, CRYST_THRESHOLD,
)

log = logging.getLogger("educe.organ_verbosity")

# ═══ 信号定义 ═══

AI_LONG_THRESHOLD = 400  # AI 回答超过此字符数视为"长回答"
USER_SHORT_THRESHOLD = 30  # 用户回复短于此视为"跳过"
SKIP_SIGNAL_WEIGHT = OBSERVE_GAIN  # 0.15
EXPLICIT_SIGNAL_WEIGHT = 0.35  # 用户显式说"简短点"

# 终结词（用户快速确认不追问）
TERMINATOR_PATTERNS = re.compile(
    r'^(ok|好的?|收到|谢|嗯|知道了|明白|got it|thanks|ty|thx|👍|可以|行)\s*[。.!！]?\s*$',
    re.IGNORECASE
)

# 追问词（用户想要更多细节）
FOLLOWUP_PATTERNS = re.compile(
    r'(为什么|怎么|能.{0,4}详细|具体|展开|再说说|解释|more detail|elaborate|why|how)',
    re.IGNORECASE
)

# 显式要求简短
EXPLICIT_SHORT_PATTERNS = re.compile(
    r'(简短|精简|简洁|简单说|别那么长|太长了|short|brief|concise|tl;?dr)',
    re.IGNORECASE
)


# ═══ Turn Meta ═══

@dataclass
class TurnMeta:
    """单轮对话元信息"""
    ai_reply_len: int = 0
    user_input_len: int = 0
    user_input: str = ""
    ts: float = field(default_factory=time.time)

    @property
    def is_ai_long(self) -> bool:
        return self.ai_reply_len > AI_LONG_THRESHOLD

    @property
    def is_user_short(self) -> bool:
        return self.user_input_len < USER_SHORT_THRESHOLD

    @property
    def is_terminator(self) -> bool:
        return bool(TERMINATOR_PATTERNS.match(self.user_input.strip()))

    @property
    def is_followup(self) -> bool:
        return bool(FOLLOWUP_PATTERNS.search(self.user_input))

    @property
    def is_explicit_short(self) -> bool:
        return bool(EXPLICIT_SHORT_PATTERNS.search(self.user_input))


# ═══ Confidence State ═══

@dataclass
class PatternState:
    """单个模式的 confidence 状态"""
    pattern_id: str
    confidence: float = 0.0
    state: str = "idle"  # idle | observing | proposed | crystallized | dismissed
    last_updated: float = field(default_factory=time.time)
    observe_count: int = 0
    confirm_count: int = 0

    def to_dict(self) -> dict:
        return {
            "confidence": round(self.confidence, 3),
            "state": self.state,
            "last_updated": self.last_updated,
            "observe_count": self.observe_count,
            "confirm_count": self.confirm_count,
        }

    @classmethod
    def from_dict(cls, pattern_id: str, d: dict) -> "PatternState":
        return cls(
            pattern_id=pattern_id,
            confidence=d.get("confidence", 0),
            state=d.get("state", "idle"),
            last_updated=d.get("last_updated", 0),
            observe_count=d.get("observe_count", 0),
            confirm_count=d.get("confirm_count", 0),
        )


class ConfidenceStore:
    """confidence_state.json 持久化"""

    def __init__(self, path: Path | None = None):
        self._path = path or Path(".educe/confidence_state.json")
        self._states: dict[str, PatternState] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for pid, d in data.items():
                    self._states[pid] = PatternState.from_dict(pid, d)
            except Exception as e:
                log.warning("Failed to load confidence state: %s", e)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {pid: ps.to_dict() for pid, ps in self._states.items()}
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, pattern_id: str) -> PatternState:
        if pattern_id not in self._states:
            self._states[pattern_id] = PatternState(pattern_id=pattern_id)
        return self._states[pattern_id]

    def update(self, pattern_id: str, delta: float, new_state: str | None = None) -> PatternState:
        ps = self.get(pattern_id)
        ps.confidence = max(0, min(1.0, ps.confidence + delta))
        if new_state:
            ps.state = new_state
        ps.last_updated = time.time()
        self._save()
        return ps

    def set_state(self, pattern_id: str, state: str) -> PatternState:
        ps = self.get(pattern_id)
        ps.state = state
        ps.last_updated = time.time()
        self._save()
        return ps


# ═══ VerbosityOrgan ═══

class VerbosityOrgan:
    """
    器官 A：verbosity 双向检测。

    热路径：append turn_meta 到 ring buffer
    冷路径：异步 worker 消费 buffer，判断信号，更新 confidence
    """

    PATTERN_SHORT = "verbosity:short"
    PATTERN_DETAIL = "verbosity:detail"
    BUFFER_SIZE = 20

    def __init__(self, bus: EvolutionBus | None = None,
                 store: ConfidenceStore | None = None):
        self._bus = bus
        self._store = store or ConfidenceStore()
        self._buffer: deque[TurnMeta] = deque(maxlen=self.BUFFER_SIZE)
        self._on_propose: list[Callable[[EvolutionEvent], Awaitable[None]]] = []
        self._reflex_fired = False

    def on_propose(self, fn: Callable[[EvolutionEvent], Awaitable[None]]):
        self._on_propose.append(fn)

    def record_turn(self, ai_reply_len: int, user_input: str):
        """热路径：记录到 ring buffer，O(1)"""
        meta = TurnMeta(
            ai_reply_len=ai_reply_len,
            user_input_len=len(user_input),
            user_input=user_input,
        )
        self._buffer.append(meta)

    async def check_signals(self) -> EvolutionEvent | None:
        """冷路径：消费最新 turn_meta，判断信号并推进状态机。

        返回 PROPOSE 事件（如果刚跨阈值），否则 None。
        """
        if not self._buffer:
            return None

        latest = self._buffer[-1]
        prev = self._buffer[-2] if len(self._buffer) >= 2 else None

        # 反射气泡检测：crystallized 后首轮 AI 回答确实变短 → 弹一次
        ps = self._store.get(self.PATTERN_SHORT)
        if ps.state == "crystallized" and not self._reflex_fired:
            if prev and prev.is_ai_long and latest.ai_reply_len < AI_LONG_THRESHOLD:
                self._reflex_fired = True
                event = EvolutionEvent(
                    kind=EvolutionKind.SHIFT,
                    organ=OrganRef(family="verbosity", id=self.PATTERN_SHORT),
                    cause="偏好已生效：回答明显变短",
                    delta={"before_len": prev.ai_reply_len, "after_len": latest.ai_reply_len},
                    phrase="已在用简短模式回答",
                    confidence=ps.confidence,
                )
                if self._bus:
                    await self._bus.emit(event)
                return event
            elif latest.ai_reply_len < AI_LONG_THRESHOLD:
                self._reflex_fired = True
            return None

        # 显式信号（"简短点"）→ 大权重
        if latest.is_explicit_short:
            return await self._advance_short(EXPLICIT_SIGNAL_WEIGHT, "用户明确要求简短回答")

        # detail_skip 信号：上一轮 AI 长回答 + 用户短回复/终结/非追问
        if prev and prev.is_ai_long and (latest.is_user_short or latest.is_terminator) and not latest.is_followup:
            return await self._advance_short(SKIP_SIGNAL_WEIGHT, "AI 长回答后用户快速跳过")

        # detail_want 信号：用户追问要细节
        if latest.is_followup:
            return await self._advance_detail(SKIP_SIGNAL_WEIGHT, "用户要求更详细")

        return None

    async def _advance_short(self, delta: float, cause: str) -> EvolutionEvent | None:
        ps = self._store.get(self.PATTERN_SHORT)

        if ps.state == "dismissed":
            return None
        if ps.state == "crystallized":
            return None

        old_conf = ps.confidence
        ps = self._store.update(self.PATTERN_SHORT, delta,
                                new_state="observing" if ps.state == "idle" else None)
        ps.observe_count += 1
        self._store._save()

        event = EvolutionEvent(
            kind=EvolutionKind.OBSERVE,
            organ=OrganRef(family="verbosity", id=self.PATTERN_SHORT),
            cause=cause,
            delta={"confidence_before": old_conf, "confidence_after": ps.confidence,
                   "direction": "short"},
            phrase=None,
            confidence=ps.confidence,
            progress={"current": ps.confidence, "threshold": HOT_THRESHOLD},
        )

        if self._bus:
            await self._bus.emit(event)

        if old_conf < HOT_THRESHOLD <= ps.confidence and ps.state != "proposed":
            return await self._emit_propose(ps)

        return None

    async def _advance_detail(self, delta: float, cause: str) -> EvolutionEvent | None:
        ps_short = self._store.get(self.PATTERN_SHORT)
        if ps_short.confidence > 0:
            self._store.update(self.PATTERN_SHORT, -delta * 0.5)

        return None

    async def _emit_propose(self, ps: PatternState) -> EvolutionEvent:
        self._store.set_state(self.PATTERN_SHORT, "proposed")

        event = EvolutionEvent(
            kind=EvolutionKind.PROPOSE,
            organ=OrganRef(family="verbosity", id=self.PATTERN_SHORT),
            cause="你最近多次跳过了详细解释",
            delta={"preference": "short", "confidence": ps.confidence},
            phrase="我注意到你可能更喜欢简短回答，要我默认精简吗？",
            confidence=ps.confidence,
            progress={"current": ps.confidence, "threshold": CRYST_THRESHOLD},
        )

        if self._bus:
            await self._bus.emit(event)

        for fn in self._on_propose:
            try:
                await fn(event)
            except Exception as e:
                log.warning("on_propose callback error: %s", e)

        return event

    async def handle_calibrate(self, action: str, event_id: str = "") -> EvolutionEvent | None:
        """处理用户校准回流"""
        ps = self._store.get(self.PATTERN_SHORT)

        if action == "confirm":
            old_conf = ps.confidence
            ps = self._store.update(self.PATTERN_SHORT, CONFIRM_JUMP)
            ps.confirm_count += 1
            self._store._save()

            if ps.confidence >= CRYST_THRESHOLD and ps.confirm_count >= 1:
                self._store.set_state(self.PATTERN_SHORT, "crystallized")
                event = EvolutionEvent(
                    kind=EvolutionKind.CRYSTALLIZE,
                    organ=OrganRef(family="verbosity", id=self.PATTERN_SHORT),
                    cause="用户确认偏好简短回答",
                    delta={"preference": "short", "crystallized": True},
                    phrase="已记住：默认给你简短回答",
                    confidence=ps.confidence,
                )
                if self._bus:
                    await self._bus.emit(event)
                return event

        elif action == "dismiss":
            self._store.set_state(self.PATTERN_SHORT, "dismissed")

        elif action == "snooze":
            self._store.update(self.PATTERN_SHORT, -0.1, new_state="observing")

        elif action == "revert":
            self._store.update(self.PATTERN_SHORT, -REVERT_DROP, new_state="observing")

        return None

    def is_crystallized(self, pattern_id: str | None = None) -> bool:
        pid = pattern_id or self.PATTERN_SHORT
        ps = self._store.get(pid)
        return ps.state == "crystallized"

    def get_verbosity_hint(self) -> str | None:
        """如果 verbosity:short 已固化，返回 system prompt 注入文本"""
        if self.is_crystallized(self.PATTERN_SHORT):
            return (
                "用户偏好简短回答。严格遵守以下约束：\n"
                "- 核心答案控制在 3 句以内\n"
                "- 不主动展开背景、举例、对比，除非被要求\n"
                "- 代码类回答只给最小可运行示例\n"
                "- 如果用户追问「详细说说」再展开"
            )
        return None
