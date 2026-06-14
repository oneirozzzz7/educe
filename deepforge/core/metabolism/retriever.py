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

        # 策略1：失败教训（有成功对照时给正确做法）
        failure_lessons = self._extract_failure_lessons(records)

        # 策略2：失败热区警告（没有成功对照，但高频失败）
        hotspot_warnings = self._extract_hotspot_warnings(records, user_input)

        # 策略3：成功模式
        success_patterns = self._extract_success_patterns(records, user_input)

        hints = []
        for lesson in failure_lessons[:2]:
            hints.append(lesson)
        for warning in hotspot_warnings[:2]:
            if warning not in hints:
                hints.append(warning)
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

    def _extract_hotspot_warnings(self, records: list[ConsequenceRecord], user_input: str) -> list[str]:
        """从高频失败区域提取警告（即使没有成功对照）"""
        warnings = []
        keywords = set(user_input.replace("，", " ").replace("。", " ").split())
        keywords = {k for k in keywords if len(k) > 1}

        # 按 pitfall_trigger 聚合失败（利用 context_snapshot 里的 pitfall 信息）
        pitfall_groups: dict[str, list[ConsequenceRecord]] = {}
        for r in records:
            if r.outcome_type not in (OutcomeType.FAILURE, OutcomeType.TIMEOUT):
                continue
            trigger = r.context_snapshot.get("pitfall_trigger", "")
            if not trigger:
                trigger = r.context_snapshot.get("user_input", "")[:30]
            pitfall_groups.setdefault(trigger, []).append(r)

        for trigger, fails in pitfall_groups.items():
            if len(fails) < 3:
                continue  # 不够频繁，不警告

            # 检查是否与当前请求相关
            trigger_keywords = set(trigger.replace("，", " ").replace("。", " ").split())
            overlap = keywords & trigger_keywords
            if not overlap and not any(k in user_input for k in trigger.split()[:2] if len(k) > 1):
                continue

            # 找最常见的失败 action
            action_counts: dict[str, int] = {}
            for f in fails:
                action_key = f"{f.decision_point}:{f.action_taken.get('params', '')[:30]}"
                action_counts[action_key] = action_counts.get(action_key, 0) + 1

            if action_counts:
                most_common = max(action_counts, key=action_counts.get)
                count = action_counts[most_common]
                # 看是否有 correct_action 提示
                correct = fails[0].outcome_detail.get("correct_action", "")
                if correct:
                    warnings.append(f"⚠️ 「{trigger}」经常失败({count}次)。正确做法：{correct}")
                else:
                    warnings.append(f"⚠️ 「{trigger}」用 {most_common} 经常失败({count}次)，注意检查")

        return warnings
