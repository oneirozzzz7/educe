"""
IterationState — 收敛过程的核心状态对象

追踪"我们知道了什么"（不是"发生了什么"，那是 SessionState/Ledger 的工作）。
每次 action 执行后，基于结果更新 claims 集合，度量收敛进展。

设计原则（来自 Opus 讨论 Round 2）：
- Checkpoint-First: 可序列化，不依赖对话历史
- Pruning-as-Progress: 进展 = 搜索空间缩小
- Attribution Chain: 每个 claim 可追溯证据来源
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class FactStatus(str, Enum):
    OPEN = "open"
    VERIFIED = "verified"
    RULED_OUT = "ruled_out"


@dataclass(frozen=True)
class Claim:
    """关于任务世界的一个可证伪陈述"""
    claim_id: str
    text: str
    status: FactStatus
    evidence: tuple[str, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0

    @staticmethod
    def new(text: str, status: FactStatus = FactStatus.OPEN,
            evidence: tuple[str, ...] = ()) -> "Claim":
        cid = hashlib.sha1(text.encode()).hexdigest()[:12]
        now = time.time()
        return Claim(cid, text, status, evidence, now, now)

    def with_status(self, status: FactStatus, evidence: tuple[str, ...] = ()) -> "Claim":
        merged = self.evidence + evidence
        return Claim(self.claim_id, self.text, status, merged,
                     self.created_at, time.time())

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "status": self.status.value,
            "evidence": list(self.evidence),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        return cls(
            claim_id=d["claim_id"],
            text=d["text"],
            status=FactStatus(d["status"]),
            evidence=tuple(d.get("evidence", [])),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
        )


@dataclass
class IterationState:
    """收敛过程的知识状态快照"""
    task_id: str
    claims: dict[str, Claim] = field(default_factory=dict)
    revision: int = 0

    def verified(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.status == FactStatus.VERIFIED]

    def ruled_out(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.status == FactStatus.RULED_OUT]

    def open_hyp(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.status == FactStatus.OPEN]

    def apply(self, claim: Claim) -> "IterationState":
        new_claims = dict(self.claims)
        new_claims[claim.claim_id] = claim
        return IterationState(self.task_id, new_claims, self.revision + 1)

    def convergence_metric(self) -> float:
        total = len(self.claims)
        if total == 0:
            return 0.0
        resolved = len(self.verified()) + len(self.ruled_out())
        return resolved / total

    def state_hash(self) -> str:
        payload = json.dumps(
            {cid: (c.status.value, c.text)
             for cid, c in sorted(self.claims.items())},
            sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "revision": self.revision,
            "claims": {cid: c.to_dict() for cid, c in self.claims.items()},
            "convergence": self.convergence_metric(),
            "hash": self.state_hash(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IterationState":
        claims = {cid: Claim.from_dict(cd) for cid, cd in d.get("claims", {}).items()}
        return cls(task_id=d["task_id"], claims=claims, revision=d.get("revision", 0))


class StateLog:
    """Append-only 状态序列 — 收敛历史（不可导出的护城河）"""

    def __init__(self, path: Path):
        self._path = path
        self._history: list[IterationState] = []

    def record(self, state: IterationState) -> None:
        self._history.append(state)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(state.to_dict(), ensure_ascii=False) + "\n")

    def latest(self) -> Optional[IterationState]:
        return self._history[-1] if self._history else None

    def diff(self, r1: int, r2: int) -> dict:
        if r1 >= len(self._history) or r2 >= len(self._history):
            return {}
        s1, s2 = self._history[r1], self._history[r2]
        v1 = {c.claim_id for c in s1.verified()}
        v2 = {c.claim_id for c in s2.verified()}
        ro1 = {c.claim_id for c in s1.ruled_out()}
        ro2 = {c.claim_id for c in s2.ruled_out()}
        return {
            "newly_verified": v2 - v1,
            "newly_ruled_out": ro2 - ro1,
            "convergence_delta": s2.convergence_metric() - s1.convergence_metric(),
        }

    def convergence_curve(self) -> list[float]:
        return [s.convergence_metric() for s in self._history]

    def load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._history.append(IterationState.from_dict(json.loads(line)))
