"""
OrganMiner — 从因果账本中自动发现器官候选

阶段4 P1：让器官从经验涌现，而非人工设计。

算法：
1. 从因果账本中提取 session 级别的 verb 序列
2. 找到反馈环模式：A(fail) → [repair steps] → A(success)
3. 按频次和复杂度排序
4. 用 OrganVerifier 判断是否满足器官判据
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from educe.core.metabolism.context_sig import action_verb

log = logging.getLogger("educe.organ_miner")


@dataclass
class OrganCandidate:
    """从因果账本中挖掘出的器官候选"""
    pattern: str                          # 描述性模式 "A(fail) → B → A(ok)"
    trigger_verb: str                     # 触发动作（失败的那个）
    repair_verbs: list[str]               # 修复步骤
    retry_verb: str                       # 重试动作
    frequency: int = 0                    # 跨 session 出现次数
    example_sessions: list[str] = field(default_factory=list)
    has_state_transfer: bool = False      # 是否有跨步骤信息依赖

    @property
    def complexity(self) -> int:
        """修复路径长度"""
        return len(self.repair_verbs)

    @property
    def is_feedback_loop(self) -> bool:
        """是否构成反馈环（trigger == retry）"""
        return self.trigger_verb == self.retry_verb


class OrganMiner:
    """从因果账本中挖掘器官候选"""

    def __init__(self, ledger_path: Path | None = None):
        self._path = ledger_path or Path(".educe/metabolism/consequence_ledger.jsonl")

    def mine(self, min_frequency: int = 3, max_repair_len: int = 4) -> list[OrganCandidate]:
        """
        挖掘器官候选。

        Args:
            min_frequency: 最低跨 session 出现次数
            max_repair_len: 修复路径最大长度（过长的不稳定）

        Returns:
            按频次排序的候选列表
        """
        records = self._load_records()
        sessions = self._group_by_session(records)
        candidates = self._find_feedback_patterns(sessions, max_repair_len)

        # 合并相同 pattern
        merged = self._merge_candidates(candidates)

        # 过滤
        result = [c for c in merged if c.frequency >= min_frequency and c.is_feedback_loop]
        result.sort(key=lambda c: (-c.frequency, -c.complexity))

        log.info(f"OrganMiner: found {len(result)} candidates (min_freq={min_frequency})")
        return result

    def _load_records(self) -> list[dict]:
        records = []
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    try:
                        records.append(json.loads(line))
                    except (json.JSONDecodeError, KeyError):
                        pass
        return records

    def _group_by_session(self, records: list[dict]) -> dict[str, list[dict]]:
        sessions: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            sid = r.get("session_id", "")[:16]
            sessions[sid].append(r)
        return sessions

    def _find_feedback_patterns(
        self, sessions: dict[str, list[dict]], max_repair_len: int
    ) -> list[OrganCandidate]:
        """在每个 session 中找 A(fail) → [B...] → A(ok) 模式"""
        candidates = []

        for sid, recs in sessions.items():
            if len(recs) < 3:
                continue

            seq = [(action_verb(r), r.get("outcome_type", "unknown")) for r in recs]

            for i in range(len(seq)):
                verb_i, outcome_i = seq[i]
                if outcome_i not in ("failure", "error"):
                    continue

                # 从 i+2 开始找同 verb 的成功
                for j in range(i + 2, min(i + 2 + max_repair_len, len(seq))):
                    verb_j, outcome_j = seq[j]
                    if verb_j == verb_i and outcome_j == "success":
                        repair_verbs = [seq[k][0] for k in range(i + 1, j)]
                        pattern = f"{verb_i}(fail) → {' → '.join(repair_verbs)} → {verb_i}(ok)"
                        candidates.append(OrganCandidate(
                            pattern=pattern,
                            trigger_verb=verb_i,
                            repair_verbs=repair_verbs,
                            retry_verb=verb_j,
                            frequency=1,
                            example_sessions=[sid],
                        ))
                        break  # 只取最短修复路径

        return candidates

    def _merge_candidates(self, candidates: list[OrganCandidate]) -> list[OrganCandidate]:
        """按结构化 pattern 合并同类候选"""
        groups: dict[tuple, OrganCandidate] = {}

        for c in candidates:
            key = (c.trigger_verb, tuple(c.repair_verbs), c.retry_verb)
            if key in groups:
                groups[key].frequency += 1
                if len(groups[key].example_sessions) < 5:
                    groups[key].example_sessions.extend(c.example_sessions)
            else:
                groups[key] = c

        return list(groups.values())

    def suggest_organ_models(self, min_frequency: int = 3) -> list[dict]:
        """
        返回建议的 OrganModel 规格（不自动创建，需人工/LLM审批）。
        """
        candidates = self.mine(min_frequency=min_frequency)
        suggestions = []

        for c in candidates[:5]:  # 最多 5 个建议
            suggestions.append({
                "pattern": c.pattern,
                "frequency": c.frequency,
                "trigger_verb": c.trigger_verb,
                "repair_verbs": c.repair_verbs,
                "complexity": c.complexity,
                "example_sessions": c.example_sessions[:3],
                "recommendation": self._recommend(c),
            })

        return suggestions

    @staticmethod
    def _recommend(c: OrganCandidate) -> str:
        if c.trigger_verb == "shell.python" and "shell.pkg" in c.repair_verbs:
            return "已实现（修复器官）"
        if c.trigger_verb == "shell.python" and "write_file" in c.repair_verbs:
            return "高优先级：脚本修复器官（修改代码后重试）"
        if c.trigger_verb == "edit_file" and "read_lines" in c.repair_verbs:
            return "中优先级：编辑修复器官（读取上下文后重试编辑）"
        if c.trigger_verb == "read_file" and "shell.nav" in c.repair_verbs:
            return "中优先级：文件定位器官（导航后重试读取）"
        return "待评估"
