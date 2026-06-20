"""
EvolutionEvent 总线 — Educe 系统升级 P0 核心

把"系统对自己做了什么的记录"和"让用户知道自己做了什么"
统一成一个事实流的多重投影。

设计原则（11 轮 Opus 讨论确认）：
- 准入三门槛：cause(因果可归属) + delta(行为可改变) + phrase(语言可翻译)
- 三层投影：logger(同步先行) / frontend(WS push) / learner(状态机更新)
- 非对称 confidence：REVERT_DROP > CONFIRM_JUMP
- CRYSTALLIZE 必须有显式 CONFIRM
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("educe.evolution_bus")


class EvolutionKind(str, Enum):
    OBSERVE = "observe"
    PROPOSE = "propose"
    SHIFT = "shift"
    CRYSTALLIZE = "crystallize"
    DEGRADE = "degrade"
    REVERT = "revert"


SCHEMA_VERSION = 1

# Confidence 参数（Round 10 确认）
OBSERVE_GAIN = 0.15
CONFIRM_JUMP = 0.40
REVERT_DROP = 0.50
DECAY_PER_DAY = 0.05
HOT_THRESHOLD = 0.70
CRYST_THRESHOLD = 0.90


@dataclass
class OrganRef:
    """器官引用"""
    family: str   # "reflex" | "verbosity" | "safety" | ...
    id: str | None = None  # observe/propose 阶段为 None

    def to_dict(self) -> dict:
        return {"family": self.family, "id": self.id}


@dataclass
class EvolutionEvent:
    """进化事件 — 总线上的原子单位"""
    kind: EvolutionKind
    organ: OrganRef
    cause: str          # 因果可归属（人话）
    delta: dict         # 行为改变内容
    phrase: str | None  # 语言可翻译（前端展示用）
    confidence: float
    progress: dict | None = None  # {"current": 0.45, "threshold": 0.70}
    ts: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:8]}")

    def passes_three_gates(self) -> bool:
        """准入三门槛"""
        if not self.cause:
            return False
        if not self.delta:
            return False
        # phrase 在 observe 阶段可以为空（静默），但 propose/shift 必须有
        if self.kind in (EvolutionKind.PROPOSE, EvolutionKind.SHIFT,
                         EvolutionKind.CRYSTALLIZE) and not self.phrase:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": self.kind.value,
            "organ": self.organ.to_dict(),
            "cause": self.cause,
            "delta": self.delta,
            "phrase": self.phrase,
            "confidence": round(self.confidence, 3),
            "progress": self.progress,
            "ts": self.ts,
            "event_id": self.event_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class CalibrateMessage:
    """校准回流 — 用户对事件的响应"""
    event_id: str
    action: str         # "confirm" | "revert" | "dismiss" | "snooze"
    note: str = ""
    counter_signal: bool = False
    client_ts: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrateMessage":
        return cls(
            event_id=d.get("event_id", ""),
            action=d.get("action", ""),
            note=d.get("note", ""),
            counter_signal=d.get("counter_signal", False),
            client_ts=d.get("client_ts", 0.0),
        )


# ═══════════════════════════════════════
#  总线实现
# ═══════════════════════════════════════

class EvolutionBus:
    """
    进化事件总线。

    - emit() 发布事件，触发三层投影
    - LoggerProjection 同步先行（真相源）
    - 其他投影异步（可失败不影响主路径）
    """

    def __init__(self, log_dir: Path | None = None):
        self._log_dir = log_dir or Path(".educe/evolution_events")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._log_dir / "events.jsonl"
        self._subscribers: list[Callable[[EvolutionEvent], Awaitable[None]]] = []

    def subscribe(self, fn: Callable[[EvolutionEvent], Awaitable[None]]) -> None:
        """注册异步订阅者（frontend/learner）"""
        self._subscribers.append(fn)

    async def emit(self, event: EvolutionEvent) -> None:
        """发布事件：同步写日志，异步分发订阅者"""
        # 1. Logger 同步先行（真相源，不能丢）
        self._write_log(event)

        # 2. 分发订阅者（await 确保执行，异常吞掉）
        for sub in self._subscribers:
            await self._safe_call(sub, event)

        log.debug(f"EvolutionBus: emitted {event.kind.value} for {event.organ.family}")

    def _write_log(self, event: EvolutionEvent) -> None:
        """同步写 JSONL 日志"""
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(event.to_json() + "\n")
        except Exception as e:
            log.error(f"Evolution log write failed: {e}")

    @staticmethod
    async def _safe_call(fn: Callable, event: EvolutionEvent) -> None:
        """安全调用订阅者，吞掉异常"""
        try:
            await fn(event)
        except Exception as e:
            log.warning(f"Evolution subscriber error: {e}")

    def replay(self, since: float = 0) -> list[EvolutionEvent]:
        """回放事件日志（用于 educe log / 重连恢复）"""
        events = []
        if self._log_file.exists():
            with open(self._log_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        if d.get("ts", 0) >= since:
                            events.append(self._dict_to_event(d))
                    except (json.JSONDecodeError, KeyError):
                        pass
        return events

    @staticmethod
    def _dict_to_event(d: dict) -> EvolutionEvent:
        return EvolutionEvent(
            kind=EvolutionKind(d["kind"]),
            organ=OrganRef(family=d["organ"]["family"], id=d["organ"].get("id")),
            cause=d.get("cause", ""),
            delta=d.get("delta", {}),
            phrase=d.get("phrase"),
            confidence=d.get("confidence", 0),
            progress=d.get("progress"),
            ts=d.get("ts", 0),
            event_id=d.get("event_id", ""),
        )


# ═══════════════════════════════════════
#  事件构建器注册表
# ═══════════════════════════════════════

class EventBuilder:
    """事件构建器基类"""
    def build(self, kwargs: dict) -> EvolutionEvent | None:
        raise NotImplementedError


class ReflexHitBuilder(EventBuilder):
    """reflex_hit → SHIFT/CRYSTALLIZE"""
    def build(self, kwargs: dict) -> EvolutionEvent | None:
        data = kwargs.get("data", {})
        skill_id = data.get("skill_id", "")
        skill_name = kwargs.get("summary", "反射命中")
        return EvolutionEvent(
            kind=EvolutionKind.SHIFT,
            organ=OrganRef(family="reflex", id=skill_id),
            cause=f"匹配到已固化的反射技能",
            delta={"skill_id": skill_id, "action": "reflex_bypass"},
            phrase=f"凭经验直接处理",
            confidence=0.95,
        )


class SkillMatchedBuilder(EventBuilder):
    """skill_matched → SHIFT"""
    def build(self, kwargs: dict) -> EvolutionEvent | None:
        data = kwargs.get("data", {})
        skill_names = data.get("skill_names", [])
        best_level = data.get("best_level", 0)
        if not skill_names:
            return None
        return EvolutionEvent(
            kind=EvolutionKind.SHIFT,
            organ=OrganRef(family="skill", id=None),
            cause=f"匹配到已编译技能 L{best_level}",
            delta={"skills": skill_names, "level": best_level},
            phrase=f"用已掌握的 {skill_names[0]} 技能处理",
            confidence=0.8,
        )


class NudgeBuilder(EventBuilder):
    """nudge_triggered → OBSERVE"""
    def build(self, kwargs: dict) -> EvolutionEvent | None:
        data = kwargs.get("data", {})
        return EvolutionEvent(
            kind=EvolutionKind.OBSERVE,
            organ=OrganRef(family="nudge", id=None),
            cause="探索停滞，触发收敛提醒",
            delta={"nudge_count": data.get("nudge_count", 0)},
            phrase=None,  # observe 静默
            confidence=0.3,
        )


class SafetyNetBuilder(EventBuilder):
    """safety_net → OBSERVE"""
    def build(self, kwargs: dict) -> EvolutionEvent | None:
        return EvolutionEvent(
            kind=EvolutionKind.OBSERVE,
            organ=OrganRef(family="safety", id=None),
            cause="检测到安全边界触发",
            delta={"type": "safety_intervention"},
            phrase=None,
            confidence=0.5,
        )


class ReflexShadowBuilder(EventBuilder):
    """reflex_shadow → OBSERVE"""
    def build(self, kwargs: dict) -> EvolutionEvent | None:
        data = kwargs.get("data", {})
        return EvolutionEvent(
            kind=EvolutionKind.OBSERVE,
            organ=OrganRef(family="reflex", id=data.get("skill_id")),
            cause="影子模式匹配（未执行，仅记录）",
            delta={"shadow": True, "skill_id": data.get("skill_id")},
            phrase=None,
            confidence=0.4,
        )


# 集中注册表：(type, name) → Builder
EVOLUTION_BUILDERS: dict[tuple[str, str], EventBuilder] = {
    ("framework", "reflex_hit"): ReflexHitBuilder(),
    ("framework", "skill_matched"): SkillMatchedBuilder(),
    ("framework", "nudge_triggered"): NudgeBuilder(),
    ("framework", "safety_net"): SafetyNetBuilder(),
    ("framework", "reflex_shadow"): ReflexShadowBuilder(),
}
