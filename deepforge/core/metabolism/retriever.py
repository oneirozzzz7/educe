"""
因果检索器 — 决策前从账本中检索相关经验

核心逻辑：
1. 根据当前 user_input 的关键词，找到历史上相似请求的 outcome
2. 提炼为简洁的"经验教训"注入 prompt
3. 让模型不重复犯同一个错误

相似度判定（阶段1 简单版）：
- 基于 action_type 聚合统计
- 基于 user_input 的关键词匹配
- 后续阶段可升级为 embedding 相似度
"""
from __future__ import annotations

import logging
from typing import Optional

from deepforge.core.metabolism.ledger import LedgerStore, ConsequenceRecord, OutcomeType

log = logging.getLogger("deepforge.metabolism")


class CausalRetriever:
    """从因果账本中检索相关经验，注入 prompt"""

    def __init__(self, ledger: LedgerStore):
        self._ledger = ledger

    async def retrieve_experience(self, user_input: str, max_hints: int = 3) -> str:
        """
        根据当前输入检索历史经验，返回可注入 prompt 的文本。
        如果没有相关经验，返回空字符串。
        """
        records = self._ledger._load_all()
        if not records:
            return ""

        # 策略1：找相同 action_type 的失败教训
        failure_lessons = self._extract_failure_lessons(records)

        # 策略2：找相似 user_input 的成功路径
        success_patterns = self._extract_success_patterns(records, user_input)

        hints = []
        # 失败教训优先（避免重蹈覆辙）
        for lesson in failure_lessons[:2]:
            hints.append(lesson)
        # 成功模式补充
        for pattern in success_patterns[:1]:
            hints.append(pattern)

        if not hints:
            return ""

        hints_text = "\n".join(f"- {h}" for h in hints[:max_hints])
        return f"\n## 历史经验（来自过去的操作反馈）\n{hints_text}\n"

    def _extract_failure_lessons(self, records: list[ConsequenceRecord]) -> list[str]:
        """从失败记录中提炼教训 — 极简、直接、可操作"""
        lessons = []
        seen = set()

        # 按 action_type 聚合
        failures_by_type: dict[str, list[ConsequenceRecord]] = {}
        successes_by_type: dict[str, list[ConsequenceRecord]] = {}

        for r in records:
            key = r.decision_point
            if r.outcome_type in (OutcomeType.FAILURE, OutcomeType.TIMEOUT, OutcomeType.USER_REJECTED):
                failures_by_type.setdefault(key, []).append(r)
            elif r.outcome_type == OutcomeType.SUCCESS:
                successes_by_type.setdefault(key, []).append(r)

        for action_type, fails in failures_by_type.items():
            successes = successes_by_type.get(action_type, [])
            if not successes:
                continue  # 没有成功对照就不给建议（避免误导）

            # 找最近一次成功的参数
            last_success = successes[-1]
            success_params = str(last_success.action_taken.get("params", ""))

            # 找最近一次失败的参数
            last_fail = fails[-1]
            fail_params = str(last_fail.action_taken.get("params", ""))

            if success_params != fail_params:
                lesson = f"{action_type} 用参数 {success_params} 更稳定（避免 {fail_params}）"
                if lesson not in seen:
                    lessons.append(lesson)
                    seen.add(lesson)

        return lessons

    def _extract_success_patterns(self, records: list[ConsequenceRecord], user_input: str) -> list[str]:
        """从成功记录中提取与当前请求相关的模式"""
        patterns = []

        # 简单关键词匹配（阶段1够用）
        keywords = set(user_input.replace("，", " ").replace("。", " ").split())
        keywords = {k for k in keywords if len(k) > 1}  # 过滤单字

        relevant_successes = []
        for r in records:
            if r.outcome_type != OutcomeType.SUCCESS:
                continue
            ctx_input = r.context_snapshot.get("user_input", "")
            # 计算关键词重叠
            ctx_keywords = set(ctx_input.replace("，", " ").replace("。", " ").split())
            overlap = keywords & ctx_keywords
            if len(overlap) >= 2:  # 至少 2 个关键词重叠
                relevant_successes.append((len(overlap), r))

        # 按相关度排序
        relevant_successes.sort(key=lambda x: x[0], reverse=True)

        for _, r in relevant_successes[:3]:
            cap = r.action_taken.get("capability", r.decision_point)
            params = str(r.action_taken.get("params", ""))[:40]
            latency = r.outcome_detail.get("latency", "?")
            patterns.append(f"类似请求成功用了 {cap}('{params}')，耗时 {latency}s")

        return patterns
