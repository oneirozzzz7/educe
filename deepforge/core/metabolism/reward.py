"""
即时奖励函数

规则打分 — 先用规则，不上模型。
简单、可解释、可调试。阶段1再引入模型评估。
"""
from __future__ import annotations

from deepforge.core.metabolism.ledger import OutcomeType


def immediate_reward(outcome_type: OutcomeType, detail: dict) -> float:
    """根据 outcome 类型和细节计算即时奖励 [-1.0, 1.0]"""

    if outcome_type == OutcomeType.SUCCESS:
        latency = detail.get("latency", 0)
        if latency < 1.0:
            return 1.0
        elif latency < 5.0:
            return 0.8
        elif latency < 15.0:
            return 0.6
        else:
            return 0.4  # 成功但很慢

    if outcome_type == OutcomeType.USER_CONFIRMED:
        return 1.0

    if outcome_type == OutcomeType.USER_REJECTED:
        return -0.8

    if outcome_type == OutcomeType.FAILURE:
        error_type = detail.get("error_type", "")
        if "timeout" in error_type.lower():
            return -0.5  # 超时比崩溃轻
        return -0.8

    if outcome_type == OutcomeType.TIMEOUT:
        return -0.5

    if outcome_type == OutcomeType.PENDING:
        return 0.0  # 等待延迟后果

    return 0.0
