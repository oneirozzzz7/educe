"""
Action Guardian — 执行层守卫

核心原则（Opus 4.8 确认）：
- Guardian 当护栏，不当顾问
- 直接改写/阻断，不把球踢回给模型
- 越确定性越好，不需要模型参与纠错
- MVP：完全匹配 + 直接改写

三档处理：
1. 高置信+有修复 → 直接改写执行（不告诉模型）
2. 高置信+无修复 → 阻断，返回结构化结果
3. 低置信 → 放行

阈值：失败率 ≥ 80% AND 样本 ≥ 5 才拦
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from educe.core.metabolism.ledger import LedgerStore, OutcomeType

log = logging.getLogger("deepforge.guardian")


@dataclass
class GuardResult:
    """守卫检查结果"""
    action: str  # "pass" | "rewrite" | "block"
    original_type: str = ""
    original_params: str = ""
    new_type: str = ""
    new_params: str = ""
    reason: str = ""


@dataclass
class GuardRule:
    """守卫规则"""
    match_type: str
    match_params: str  # 完全匹配
    new_params: str  # 改写目标（空=阻断）
    reason: str
    failure_rate: float
    sample_count: int


class ActionGuardian:
    """执行层守卫 — 在 action 执行前检查并改写/阻断"""

    FAILURE_THRESHOLD = 0.80  # 失败率 ≥ 80% 才拦
    MIN_SAMPLES = 5  # 最少出现 5 次才有统计意义

    def __init__(self, ledger: LedgerStore):
        self._ledger = ledger
        self._rules: list[GuardRule] = []
        self._intercept_count = 0
        self._pass_count = 0

    async def build_rules(self) -> None:
        """从账本数据中自动提取守卫规则"""
        records = self._ledger._load_all()
        if not records:
            return

        # 按 (action_type, params) 签名聚合
        signatures: dict[tuple[str, str], dict] = {}
        for r in records:
            key = (r.decision_point, r.action_taken.get("params", "").strip())
            if key not in signatures:
                signatures[key] = {"total": 0, "failures": 0, "successes": []}
            signatures[key]["total"] += 1
            if r.outcome_type in (OutcomeType.FAILURE, OutcomeType.TIMEOUT):
                signatures[key]["failures"] += 1
            elif r.outcome_type == OutcomeType.SUCCESS:
                signatures[key]["successes"].append(r.action_taken.get("params", ""))

        # 对每个高失败签名，寻找同类型的成功替代
        success_by_type: dict[str, list[str]] = {}
        for r in records:
            if r.outcome_type == OutcomeType.SUCCESS:
                success_by_type.setdefault(r.decision_point, []).append(
                    r.action_taken.get("params", "").strip()
                )

        for (action_type, params), stats in signatures.items():
            if stats["total"] < self.MIN_SAMPLES:
                continue
            failure_rate = stats["failures"] / stats["total"]
            if failure_rate < self.FAILURE_THRESHOLD:
                continue

            # 找这个 action_type 的成功参数
            successes = success_by_type.get(action_type, [])
            if successes:
                # 取最常用的成功参数
                from collections import Counter
                most_common = Counter(successes).most_common(1)[0][0]
                new_params = most_common
                reason = f"{action_type}('{params}') 历史失败率 {failure_rate:.0%}({stats['total']}次)，自动改写为 '{new_params}'"
            else:
                new_params = ""
                reason = f"{action_type}('{params}') 历史失败率 {failure_rate:.0%}({stats['total']}次)，无已知替代方案"

            self._rules.append(GuardRule(
                match_type=action_type,
                match_params=params,
                new_params=new_params,
                reason=reason,
                failure_rate=failure_rate,
                sample_count=stats["total"],
            ))

        log.info("Guardian: built %d rules from %d records", len(self._rules), len(records))
        for r in self._rules:
            log.info("  Rule: %s('%s') → '%s' (rate=%.0f%%, n=%d)",
                     r.match_type, r.match_params, r.new_params, r.failure_rate*100, r.sample_count)

    def check(self, action_type: str, params: str) -> GuardResult:
        """检查 action 是否命中守卫规则"""
        params_clean = params.strip()

        # 硬规则：read_dir/read_file 的 JSON 参数自动提取 path
        if action_type in ("read_dir", "read_file") and params_clean.startswith("{"):
            try:
                import json
                parsed = json.loads(params_clean)
                if "path" in parsed:
                    new_params = parsed["path"]
                    self._intercept_count += 1
                    log.info("Guardian REWRITE: %s('%s') → '%s' (JSON→path extraction)",
                             action_type, params_clean[:40], new_params)
                    return GuardResult(
                        action="rewrite",
                        original_type=action_type,
                        original_params=params_clean,
                        new_type=action_type,
                        new_params=new_params,
                        reason=f"参数格式修正：JSON → 纯路径 '{new_params}'",
                    )
            except (ValueError, TypeError):
                pass

        # 数据驱动规则（从账本自动提取）
        for rule in self._rules:
            if rule.match_type == action_type and rule.match_params == params_clean:
                self._intercept_count += 1

                if rule.new_params:
                    log.info("Guardian REWRITE: %s('%s') → '%s' | %s",
                             action_type, params_clean, rule.new_params, rule.reason)
                    return GuardResult(
                        action="rewrite",
                        original_type=action_type,
                        original_params=params_clean,
                        new_type=action_type,
                        new_params=rule.new_params,
                        reason=rule.reason,
                    )
                else:
                    log.info("Guardian BLOCK: %s('%s') | %s", action_type, params_clean, rule.reason)
                    return GuardResult(
                        action="block",
                        original_type=action_type,
                        original_params=params_clean,
                        reason=rule.reason,
                    )

        self._pass_count += 1
        return GuardResult(action="pass")

    @property
    def stats(self) -> dict:
        return {
            "rules": len(self._rules),
            "intercepts": self._intercept_count,
            "passes": self._pass_count,
        }
