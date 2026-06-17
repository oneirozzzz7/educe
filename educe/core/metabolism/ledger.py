"""
因果账本（Consequence Ledger）

Educe 代谢回路的传感器层。每个决策点记录三元组：
(context_snapshot, action_taken, outcome)

这是整个进化引擎的数据基础 — 没有可观测的后果，
"固化或淘汰"就没有依据。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("educe.metabolism")


class OutcomeType(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    USER_CONFIRMED = "user_confirmed"
    USER_REJECTED = "user_rejected"
    TIMEOUT = "timeout"
    PENDING = "pending"  # 延迟后果占位，阶段1回填


@dataclass
class ConsequenceRecord:
    """因果记录 — 代谢系统的原子单位"""
    record_id: str
    session_id: str
    seed_id: str
    round_idx: int
    decision_point: str          # 决策树节点（action type）
    context_snapshot: dict        # 裁剪过的决策上下文
    action_taken: dict            # capability 名 + 参数
    outcome_type: OutcomeType
    outcome_detail: dict          # 返回值/报错/用户反馈
    immediate_reward: float       # -1.0 ~ 1.0
    seq: int = -1                 # session 全局递增序号（阶段2序列归属）
    delayed_outcome_ref: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["outcome_type"] = self.outcome_type.value
        return d


class LedgerStore:
    """因果账本存储 — 基于 JSONL 文件的简单实现"""

    def __init__(self, base_dir: Path):
        self._dir = base_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "consequence_ledger.jsonl"

    async def append(self, record: ConsequenceRecord) -> None:
        """追加一条因果记录"""
        line = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(line)
        log.debug("Ledger: recorded %s %s → %s",
                  record.decision_point, record.action_taken.get("capability", ""),
                  record.outcome_type.value)

    async def query_by_session(self, session_id: str) -> list[ConsequenceRecord]:
        """查询某个 session 的所有因果记录"""
        return [r for r in self._load_all() if r.session_id == session_id]

    async def query_by_action_type(self, action_type: str, limit: int = 50) -> list[ConsequenceRecord]:
        """查询某类 action 的历史记录"""
        results = []
        for r in reversed(self._load_all()):
            if r.decision_point == action_type:
                results.append(r)
                if len(results) >= limit:
                    break
        return results

    async def query_failure_stats(self, days: int = 7) -> dict[str, dict]:
        """查询最近 N 天的失败统计"""
        cutoff = time.time() - days * 86400
        stats: dict[str, dict] = {}
        for r in self._load_all():
            if r.created_at < cutoff:
                continue
            key = r.decision_point
            if key not in stats:
                stats[key] = {"total": 0, "failures": 0, "avg_reward": 0.0, "rewards": []}
            stats[key]["total"] += 1
            stats[key]["rewards"].append(r.immediate_reward)
            if r.outcome_type in (OutcomeType.FAILURE, OutcomeType.TIMEOUT, OutcomeType.USER_REJECTED):
                stats[key]["failures"] += 1

        for key, s in stats.items():
            s["avg_reward"] = sum(s["rewards"]) / len(s["rewards"]) if s["rewards"] else 0
            s["failure_rate"] = s["failures"] / s["total"] if s["total"] else 0
            del s["rewards"]

        return stats

    async def count(self) -> int:
        """总记录数"""
        if not self._file.exists():
            return 0
        with open(self._file, "r") as f:
            return sum(1 for _ in f)

    def _load_all(self) -> list[ConsequenceRecord]:
        """加载全部记录（小规模足够，大规模需要索引）"""
        if not self._file.exists():
            return []
        records = []
        with open(self._file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    d["outcome_type"] = OutcomeType(d["outcome_type"])
                    d.setdefault("seq", -1)
                    records.append(ConsequenceRecord(**d))
                except Exception:
                    continue
        return records
