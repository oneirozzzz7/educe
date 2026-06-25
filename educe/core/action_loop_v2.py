"""Action Loop V2 — Plan-aware 循环

核心改变：
1. 模型维护 <plan> 块（自知状态）
2. status=done 时自行终止（无 max_rounds 硬墙）
3. 三层滑动窗口压缩（hot/warm/frozen）
4. wall_clock 120s 超时兜底
5. Pinned plan 每轮注入

调用方式：
    result = await action_loop_v2(orchestrator, user_input, system, messages, client, ...)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from educe.core.plan_parser import parse_plan, _PLAN_RE
from educe.core.loop_context import LoopContext, TurnRecord, PIN_LABEL

log = logging.getLogger("educe.loop_v2")


def _strip_plan(text: str) -> str:
    """从文本中移除 <plan>...</plan> 块，只留给用户看的内容。"""
    return _PLAN_RE.sub("", text).strip()

WALL_CLOCK_TIMEOUT = 120  # 秒


async def action_loop_v2(
    orch: Any,
    user_input: str,
    system_prompt: str,
    initial_messages: list[dict],
    client: Any,
    file_context: str = "",
) -> dict:
    """新 action loop：Plan-aware + 压缩窗口 + 无 max_rounds。

    返回 {"final_reply": str, "reason": str, "rounds": int}
    """
    from educe.core.action_executor import parse_actions

    loop_ctx = LoopContext()
    messages = list(initial_messages)  # 浅拷贝，不影响原始

    # 用户输入
    user_content = user_input
    if file_context:
        user_content = f"{user_input}\n\n{file_context}"
    messages.append({"role": "user", "content": user_content})

    final_reply = ""
    round_idx = 0
    start_time = time.monotonic()

    while True:
        # Wall clock 超时检查
        elapsed = time.monotonic() - start_time
        if elapsed > WALL_CLOCK_TIMEOUT:
            log.warning("loop_v2 | wall clock timeout at round %d (%.0fs)", round_idx, elapsed)
            break

        # 注入 Situation（第 2 轮起）
        if hasattr(orch, 'effects'):
            orch.effects.set_round(round_idx)
            situation_text = orch.effects.situation.render_for_model()
            if situation_text:
                messages.append({"role": "user", "content": situation_text})

        # Pinned Plan（第 2 轮起注入，第 1 轮还没有 plan）
        messages = [m for m in messages if not m.get("content", "").startswith(PIN_LABEL)]
        if loop_ctx.current_plan and round_idx >= 1:
            messages.append({"role": "user", "content": f"{PIN_LABEL}\n{loop_ctx.current_plan.to_block()}"})

        # 压缩检查
        loop_ctx.compress_if_needed()

        # 调用 LLM
        log.info("loop_v2 | round=%d msgs=%d elapsed=%.1fs", round_idx, len(messages), elapsed)
        try:
            raw = await asyncio.wait_for(
                client.chat(
                    messages=messages,
                    model=orch.config.default_model.model,
                    max_tokens=orch.config.default_model.max_tokens,
                ),
                timeout=120,
            )
        except asyncio.TimeoutError:
            log.error("loop_v2 | round %d LLM timeout", round_idx)
            break
        except Exception as e:
            log.error("loop_v2 | round %d LLM error: %s", round_idx, str(e)[:100])
            break

        if not raw or not raw.strip():
            log.warning("loop_v2 | round %d empty response", round_idx)
            break

        # 解析 plan + actions
        new_plan = parse_plan(raw)
        loop_ctx.update_plan(new_plan)
        reply_text, actions = parse_actions(raw)

        # status=done → 模型自己决定结束
        if loop_ctx.is_done():
            text = _strip_plan(reply_text or raw)
            if text:
                for i in range(0, len(text), 20):
                    orch._notify_chunk("assistant", text[i:i+20])
            final_reply = text
            if hasattr(orch, 'state') and text:
                orch.state.add_ai_reply(text)
            break

        # 无 action → 推送回复给用户 → 结束
        if not actions:
            text = _strip_plan(reply_text or raw)
            if text:
                for i in range(0, len(text), 20):
                    orch._notify_chunk("assistant", text[i:i+20])
            final_reply = text
            if hasattr(orch, 'state') and text:
                orch.state.add_ai_reply(text)
            break

        # 有 action → 检查不可逆 → 执行
        from educe.core.irreversibility import is_irreversible

        # 分离：不可逆的需确认，其余直接执行
        pending_confirm = [a for a in actions if is_irreversible(a)]
        immediate = [a for a in actions if a not in pending_confirm]

        # 不可逆动作 → 触发 confirm 流程，暂停 loop
        if pending_confirm:
            import json as _json_cf
            from educe.core.orchestrator import Message, MessageType
            confirm_items = [{"type": a.type, "params": a.params, "name": a.name,
                              "display": f"{a.type}: {a.params[:60]}"} for a in pending_confirm]
            orch.context.metadata["_pending_actions"] = confirm_items
            orch.context.metadata["_pending_user_input"] = user_input
            confirm_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                content="__ACTION_CONFIRM__" + _json_cf.dumps(confirm_items, ensure_ascii=False))
            orch._notify(confirm_msg)
            # Loop 暂停，等用户确认（server.py 处理 confirm response）
            return {"final_reply": "", "reason": "confirm_pending", "rounds": round_idx}

        # assistant 原始输出追加一次
        messages.append({"role": "assistant", "content": raw})

        for action in immediate:

            # 执行 action
            result = await orch._execute_action(action, user_input, None)

            # 推送 action detail 事件
            _emit_action_detail(orch, action, result, round_idx)

            # 结果追加到 messages
            output = result.get("output", "")[:500]
            success = result.get("success", False)
            messages.append({"role": "user", "content":
                f"[系统] {'✓' if success else '✗'} {action.type} 结果：{output}"})

            # 记录到 loop context
            loop_ctx.add_turn(TurnRecord(
                round_idx=round_idx,
                assistant_raw=raw,
                action_type=action.type,
                action_params=action.params[:100],
                result_output=output,
                success=success,
            ))

            # Effect 记录
            if hasattr(orch, 'effects') and action.type == "shell":
                orch.effects.emit("shell",
                    intent={"cmd": action.params[:60]},
                    outcome={"exit_code": result.get("exit_code", 0)})

        # 如果有 reply_text（"说了再做"），推送给用户
        if reply_text:
            clean_reply = _strip_plan(reply_text)
            if clean_reply:
                for i in range(0, len(clean_reply), 20):
                    orch._notify_chunk("assistant", clean_reply[i:i+20])
                if hasattr(orch, 'state'):
                    orch.state.add_ai_reply(clean_reply)

        round_idx += 1

    # Loop 结束后：如果没有 final_reply（超时等），做保底总结
    if not final_reply and round_idx > 0:
        try:
            messages.append({"role": "user", "content":
                "[系统] 请基于已有信息直接给出简洁总结回复。"})
            summary = await asyncio.wait_for(
                client.chat(messages=messages, model=orch.config.default_model.model,
                            max_tokens=orch.config.default_model.max_tokens),
                timeout=30)
            if summary and summary.strip():
                text = summary.strip()
                for i in range(0, len(text), 20):
                    orch._notify_chunk("assistant", text[i:i+20])
                final_reply = text
                if hasattr(orch, 'state'):
                    orch.state.add_ai_reply(text)
        except Exception as e:
            log.warning("loop_v2 | summary call failed: %s", str(e)[:100])

    # 写入 conversation
    if final_reply:
        orch.conversation.add_assistant(final_reply)

    return {
        "final_reply": final_reply,
        "reason": "done" if loop_ctx.is_done() else ("timeout" if time.monotonic() - start_time > WALL_CLOCK_TIMEOUT else "no_action"),
        "rounds": round_idx,
    }


def _emit_action_detail(orch, action, result, round_idx):
    """推送 action detail 事件给前端。"""
    import json as _json
    try:
        from educe.core.orchestrator import Message, MessageType
        evt = {
            "event": "action_detail",
            "action_type": action.type,
            "name": action.type,
            "summary": f"{action.type} {action.params[:60]}",
            "success": result.get("success", False),
        }
        msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                      content="__TOOL_EVENT__" + _json.dumps(evt, ensure_ascii=False))
        orch._notify(msg)
    except Exception:
        pass
