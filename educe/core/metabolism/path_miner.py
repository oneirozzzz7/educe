"""
PathMiner — 阶段2路径挖掘器 MVP

从因果账本中挖掘重复稳定的多步决策序列（PathCandidate），
为 CompositeSkill 编译提供原料。

算法：n-gram 滑窗 + task_type 分域 + 三重过滤 + position_profile 后置标注

设计原则：
- support 用跨 session 数，不用出现次数（掐掉单 session 循环噪声）
- 长路径吸收子路径
- 自适应降级：稀疏域自动降低 sig level
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from educe.core.metabolism.context_sig import (
    StepSig,
    project_sig,
    task_type,
)
from educe.core.metabolism.ledger import LedgerStore


@dataclass
class PositionProfile:
    """路径在 session 中的位置画像"""
    mean_norm_pos: float = 0.0
    std_norm_pos: float = 0.0
    is_starter: bool = False      # 总在 session 开头 (norm_pos < 0.2)
    is_positional: bool = False   # std < 0.15 → 位置敏感


@dataclass
class PathCandidate:
    """路径候选 — 可编译为 CompositeSkill 的原料"""
    steps: tuple[StepSig, ...]
    scope: str                            # task_type 域
    support: int                          # 跨 session 出现次数
    session_ids: list[str] = field(default_factory=list)
    mean_reward: float = 0.0
    reward_variance: float = 0.0
    mean_token_cost: int = 0
    position: PositionProfile = field(default_factory=PositionProfile)

    @property
    def length(self) -> int:
        return len(self.steps)

    @property
    def decision_steps_saved(self) -> int:
        return self.length - 1

    def __str__(self) -> str:
        steps_str = " → ".join(str(s) for s in self.steps)
        return f"[{self.scope}] sup={self.support} {steps_str}"

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_tuple() for s in self.steps],
            "scope": self.scope,
            "support": self.support,
            "session_ids": self.session_ids[:10],
            "mean_reward": round(self.mean_reward, 3),
            "reward_variance": round(self.reward_variance, 4),
            "position": {
                "mean_norm_pos": round(self.position.mean_norm_pos, 3),
                "std_norm_pos": round(self.position.std_norm_pos, 3),
                "is_starter": self.position.is_starter,
                "is_positional": self.position.is_positional,
            },
        }


class PathMiner:
    """路径挖掘器 — 从账本中挖掘可编译路径"""

    def __init__(
        self,
        min_support: int = 3,
        min_reward: float = 0.3,
        max_variance: float = 0.8,
        ngram_range: tuple[int, int] = (2, 4),
        sig_level: int = 2,
    ):
        self.min_support = min_support
        self.min_reward = min_reward
        self.max_variance = max_variance
        self.ngram_range = ngram_range
        self.sig_level = sig_level

    def mine(self, records: list[dict]) -> list[PathCandidate]:
        """主入口：从 ConsequenceRecord dicts 中挖掘路径候选"""
        # 按 session 分组，按时间排序
        sessions = self._group_by_session(records)

        # 按 task_type 分域独立挖掘
        all_candidates: list[PathCandidate] = []
        for scope, scope_sessions in self._partition_by_scope(sessions).items():
            level = self._adaptive_level(scope_sessions)
            candidates = self._mine_scope(scope, scope_sessions, level)
            all_candidates.extend(candidates)

        # 去重：长路径吸收子路径
        all_candidates = self._dedup_subsume(all_candidates)

        # 按 support 降序
        all_candidates.sort(key=lambda c: -c.support)
        return all_candidates

    def mine_from_ledger(self, ledger_path: Path | str) -> list[PathCandidate]:
        """从 JSONL 文件直接挖掘"""
        records = self._load_jsonl(Path(ledger_path))
        return self.mine(records)

    # ═══════════════════════════════════════
    #  内部方法
    # ═══════════════════════════════════════

    def _group_by_session(self, records: list[dict]) -> dict[str, list[dict]]:
        sessions: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            sessions[r["session_id"]].append(r)
        for sid in sessions:
            sessions[sid].sort(key=lambda x: x.get("created_at", x.get("seq", 0)))
        return dict(sessions)

    def _partition_by_scope(
        self, sessions: dict[str, list[dict]]
    ) -> dict[str, dict[str, list[dict]]]:
        """将 sessions 按首条 user_input 的 task_type 分域"""
        scoped: dict[str, dict[str, list[dict]]] = defaultdict(dict)
        for sid, recs in sessions.items():
            ui = recs[0].get("context_snapshot", {}).get("user_input", "") if recs else ""
            scope = task_type(ui)
            scoped[scope][sid] = recs
        return dict(scoped)

    def _adaptive_level(self, scope_sessions: dict[str, list[dict]]) -> int:
        """根据域的数据量自适应选择 sig level"""
        total = sum(len(recs) for recs in scope_sessions.values())
        if total < 30:
            return 0
        if total < 100:
            return 1
        return self.sig_level

    def _mine_scope(
        self,
        scope: str,
        sessions: dict[str, list[dict]],
        level: int,
    ) -> list[PathCandidate]:
        """在单个域内挖掘 n-gram 路径"""
        # 提取 n-grams，记录 (session_id, start_pos, session_len, rewards)
        ngram_data: dict[tuple, list[dict]] = defaultdict(list)

        for sid, recs in sessions.items():
            sig_seq = [project_sig(r, level=level) for r in recs]
            rewards = [r.get("immediate_reward", 0.0) for r in recs]
            sess_len = len(sig_seq)

            for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
                for i in range(len(sig_seq) - n + 1):
                    gram = tuple(sig_seq[i:i + n])
                    gram_rewards = rewards[i:i + n]
                    ngram_data[gram].append({
                        "session_id": sid,
                        "start_pos": i,
                        "session_len": sess_len,
                        "rewards": gram_rewards,
                    })

        # 三重过滤
        candidates: list[PathCandidate] = []
        for gram, occurrences in ngram_data.items():
            # Support: 跨 session 数
            unique_sessions = set(o["session_id"] for o in occurrences)
            support = len(unique_sessions)
            if support < self.min_support:
                continue

            # Mean reward
            all_rewards = [r for o in occurrences for r in o["rewards"]]
            mr = mean(all_rewards) if all_rewards else 0.0
            if mr < self.min_reward:
                continue

            # Reward variance
            rv = stdev(all_rewards) if len(all_rewards) > 1 else 0.0
            if rv > self.max_variance:
                continue

            # Position profile
            positions = [
                (o["start_pos"], o["session_len"]) for o in occurrences
            ]
            pos_profile = self._compute_position_profile(positions)

            candidates.append(PathCandidate(
                steps=gram,
                scope=scope,
                support=support,
                session_ids=list(unique_sessions)[:10],
                mean_reward=mr,
                reward_variance=rv,
                position=pos_profile,
            ))

        return candidates

    def _compute_position_profile(
        self, positions: list[tuple[int, int]]
    ) -> PositionProfile:
        """计算路径的位置画像"""
        if not positions:
            return PositionProfile()

        norm_pos = [s / max(l - 1, 1) for s, l in positions]
        m = mean(norm_pos) if norm_pos else 0.0
        s = stdev(norm_pos) if len(norm_pos) > 1 else 0.0

        return PositionProfile(
            mean_norm_pos=m,
            std_norm_pos=s,
            is_starter=m < 0.2 and s < 0.2,
            is_positional=s < 0.15,
        )

    def _dedup_subsume(self, candidates: list[PathCandidate]) -> list[PathCandidate]:
        """长路径吸收子路径：若 A 是 B 的子序列且 support 差距 < 2x，移除 A"""
        candidates.sort(key=lambda c: -c.length)
        kept: list[PathCandidate] = []

        for cand in candidates:
            subsumed = False
            for longer in kept:
                if longer.length > cand.length and longer.scope == cand.scope:
                    if self._is_subsequence(cand.steps, longer.steps):
                        if longer.support >= cand.support * 0.5:
                            subsumed = True
                            break
            if not subsumed:
                kept.append(cand)

        return kept

    @staticmethod
    def _is_subsequence(short: tuple, long: tuple) -> bool:
        """检查 short 是否是 long 的连续子序列"""
        n = len(short)
        for i in range(len(long) - n + 1):
            if long[i:i + n] == short:
                return True
        return False

    @staticmethod
    def _load_jsonl(path: Path) -> list[dict]:
        """加载 JSONL 文件"""
        if not path.exists():
            return []
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except (json.JSONDecodeError, Exception):
                    continue
        return records

    def report(self, candidates: list[PathCandidate]) -> str:
        """生成人类可读的挖掘报告"""
        lines = [f"=== Path Mining Report ===", f"Total candidates: {len(candidates)}", ""]

        by_scope: dict[str, list[PathCandidate]] = defaultdict(list)
        for c in candidates:
            by_scope[c.scope].append(c)

        for scope in sorted(by_scope.keys()):
            cands = by_scope[scope]
            lines.append(f"--- [{scope}] ({len(cands)} patterns) ---")
            for c in cands[:10]:
                pos_tag = ""
                if c.position.is_starter:
                    pos_tag = " 🚀starter"
                elif c.position.is_positional:
                    pos_tag = " 📍positional"
                lines.append(
                    f"  sup={c.support:2d} reward={c.mean_reward:.2f} "
                    f"{' → '.join(str(s) for s in c.steps)}{pos_tag}"
                )
            lines.append("")

        return "\n".join(lines)
