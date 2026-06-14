"""
Outcome Capturer — 在 action 执行处包一层，捕获后果写入账本

最小侵入设计：不改 connector/action_executor 本身，
只在调用处 wrap 一层。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Awaitable

from deepforge.core.metabolism.ledger import (
    ConsequenceRecord, LedgerStore, OutcomeType,
)
from deepforge.core.metabolism.reward import immediate_reward

log = logging.getLogger("deepforge.metabolism")


class OutcomeCapturer:
    """在 action 执行处捕获后果，写入因果账本"""

    def __init__(self, ledger: LedgerStore):
        self._ledger = ledger

    async def capture(
        self,
        session_id: str,
        seed_id: str,
        round_idx: int,
        decision_point: str,
        context: dict,
        action_meta: dict,
        action_fn: Callable[[], Awaitable[dict]],
    ) -> dict:
        """
        包装 action 执行，捕获后果。

        Args:
            session_id: 当前会话 ID
            seed_id: 当前 seed 标识
            round_idx: action loop 轮次
            decision_point: 决策点标识（action type）
            context: 决策时上下文快照（已裁剪）
            action_meta: action 元信息（capability, params 等）
            action_fn: 实际执行函数，返回 {"success": bool, "output": str}

        Returns:
            action_fn 的原始返回值
        """
        record_id = str(uuid.uuid4())[:12]
        t0 = time.time()

        try:
            result = await action_fn()
            latency = time.time() - t0

            if result.get("success", False):
                outcome_type = OutcomeType.SUCCESS
            else:
                outcome_type = OutcomeType.FAILURE

            detail = {
                "latency": round(latency, 3),
                "output_preview": str(result.get("output", ""))[:200],
                "success": result.get("success", False),
            }

        except TimeoutError:
            outcome_type = OutcomeType.TIMEOUT
            detail = {"latency": time.time() - t0, "error_type": "TimeoutError"}
            result = {"success": False, "output": "操作超时"}

        except Exception as e:
            outcome_type = OutcomeType.FAILURE
            detail = {
                "latency": time.time() - t0,
                "error_type": type(e).__name__,
                "error_msg": str(e)[:200],
            }
            result = {"success": False, "output": f"执行失败: {str(e)[:200]}"}

        # 计算即时奖励
        reward = immediate_reward(outcome_type, detail)

        # 写入账本
        record = ConsequenceRecord(
            record_id=record_id,
            session_id=session_id,
            seed_id=seed_id,
            round_idx=round_idx,
            decision_point=decision_point,
            context_snapshot=self._snapshot_context(context),
            action_taken=action_meta,
            outcome_type=outcome_type,
            outcome_detail=detail,
            immediate_reward=reward,
        )
        await self._ledger.append(record)

        log.info("Consequence: %s.%s → %s (reward=%.2f, %.1fs)",
                 decision_point, action_meta.get("capability", ""),
                 outcome_type.value, reward, detail.get("latency", 0))

        return result

    async def record_user_feedback(
        self,
        session_id: str,
        seed_id: str,
        decision_point: str,
        action_meta: dict,
        confirmed: bool,
    ) -> None:
        """记录用户确认/拒绝作为后果"""
        outcome_type = OutcomeType.USER_CONFIRMED if confirmed else OutcomeType.USER_REJECTED
        reward = immediate_reward(outcome_type, {})

        record = ConsequenceRecord(
            record_id=str(uuid.uuid4())[:12],
            session_id=session_id,
            seed_id=seed_id,
            round_idx=-1,
            decision_point=decision_point,
            context_snapshot={},
            action_taken=action_meta,
            outcome_type=outcome_type,
            outcome_detail={"confirmed": confirmed},
            immediate_reward=reward,
        )
        await self._ledger.append(record)

    def _snapshot_context(self, context: dict) -> dict:
        """裁剪上下文快照 — 只保留决策相关字段，不存全量"""
        snap = {}
        for key in ("user_input", "phase", "round", "last_action", "model"):
            if key in context:
                val = context[key]
                if isinstance(val, str) and len(val) > 200:
                    val = val[:200] + "..."
                snap[key] = val
        return snap
