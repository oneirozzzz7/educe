"""
DeepForge CognitiveState（认知黑板）
框架所有模块的共享状态——每个模块可以读写，让信息在模块间流动。

设计哲学：不加模块改连接。现有模块是能力层，CognitiveState是它们之间的信息总线。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CognitiveState:
    # ═══ 意图层（ContextAnalyzer写入）═══
    intent_clarity: str = "clear"
    detected_topic: str = ""
    reference_target: str = ""

    # ═══ 能力层（QualityTracker + ActivationEvolver写入）═══
    task_success_rate: float = 0.8
    best_seed: str = ""
    domain: str = ""

    # ═══ 用户层（UserProfile写入）═══
    user_expertise: str = "intermediate"
    user_preference: str = "detailed"

    # ═══ 对话层（框架自动维护）═══
    phase: str = "opening"
    turn_count: int = 0
    last_relevance: float = 1.0

    # ═══ 信心层（CredibilityEngine写入）═══
    framework_confidence: str = "medium"

    def should_clarify(self) -> bool:
        return self.intent_clarity == "vague"

    def should_propose_plans(self) -> bool:
        return (self.intent_clarity == "partial"
                and self.task_success_rate < 0.7)

    def should_warn(self) -> bool:
        return self.task_success_rate < 0.5

    def to_dict(self) -> dict:
        return {
            "intent_clarity": self.intent_clarity,
            "detected_topic": self.detected_topic,
            "task_success_rate": self.task_success_rate,
            "domain": self.domain,
            "phase": self.phase,
            "turn_count": self.turn_count,
            "last_relevance": self.last_relevance,
            "framework_confidence": self.framework_confidence,
            "user_expertise": self.user_expertise,
            "user_preference": self.user_preference,
        }
