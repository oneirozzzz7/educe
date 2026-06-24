"""Decision Ledger — Phase 0 埋点

记录框架每个隐式决策点的 who/what/context/outcome。
纯记录，零行为变更。用于审计"框架到底替模型做了多少决策"。

设计文档：docs/BOUNDARY_REDESIGN.md Phase 0
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class DecisionRecord:
    timestamp: float
    decision_point: str       # 决策点标识（如 "confirm_gate", "nudge", "reflex_bypass"）
    who_decided: str          # "framework" | "model" | "user"
    what: str                 # 决策内容（如 "block shell: rm -rf /", "inject nudge"）
    context: dict = field(default_factory=dict)  # 决策上下文
    outcome: Optional[str] = None  # 决策结果（事后填）


class DecisionLedger:
    """记录框架的所有隐式决策，用于审计。"""

    def __init__(self, session_dir: Optional[Path] = None):
        self._records: list[DecisionRecord] = []
        self._session_dir = session_dir
        self._file: Optional[Path] = None
        if session_dir:
            session_dir.mkdir(parents=True, exist_ok=True)
            self._file = session_dir / "decision_ledger.jsonl"

    def record(self, decision_point: str, who_decided: str, what: str,
               context: Optional[dict] = None, outcome: Optional[str] = None) -> DecisionRecord:
        """记录一条决策。"""
        rec = DecisionRecord(
            timestamp=time.time(),
            decision_point=decision_point,
            who_decided=who_decided,
            what=what,
            context=context or {},
            outcome=outcome,
        )
        self._records.append(rec)
        if self._file:
            with open(self._file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        return rec

    def summary(self) -> dict:
        """生成审计摘要。"""
        by_point = {}
        by_who = {"framework": 0, "model": 0, "user": 0}
        for r in self._records:
            by_point[r.decision_point] = by_point.get(r.decision_point, 0) + 1
            if r.who_decided in by_who:
                by_who[r.who_decided] += 1
        return {
            "total_decisions": len(self._records),
            "by_decision_point": by_point,
            "by_who": by_who,
        }

    @property
    def records(self) -> list[DecisionRecord]:
        return self._records
