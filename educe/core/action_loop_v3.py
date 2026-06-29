"""Action Loop V3 — 基于 ConversationTruth 的单一数据源循环

彻底解决 V2 的"两套数据源"问题：
- messages 每轮从 truth.project() 重建（不手动 append）
- 注入项（env/plan/situation/challenge）在 state 层
- 压缩 = 改 tier，配对组同进退
- action_history 永不被压缩影响
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from educe.core.conversation_truth import ConversationTruth, InjectionState
from educe.core.plan_parser import parse_plan, _PLAN_RE

log = logging.getLogger("educe.loop_v3")

WALL_CLOCK_TIMEOUT = 120
HARD_ROUND_CAP = 50
CHALLENGE_COOLDOWN = 2


_CHALLENGE_RE = re.compile(r'<challenge>[\s\S]*?</challenge>', re.IGNORECASE)


def _strip_plan(text: str) -> str:
    """从文本中移除 <plan>/<challenge>/action 标签，只留给用户看的内容。"""
    text = _PLAN_RE.sub("", text)
    text = _CHALLENGE_RE.sub("", text)
    from educe.core.action_executor import _NATURAL_XML_PATTERN, _XML_ACTION_PATTERN
    text = _NATURAL_XML_PATTERN.sub("", text)
    text = _XML_ACTION_PATTERN.sub("", text)
    return text.strip()


def _load_skill(name: str) -> str:
    from pathlib import Path
    skill_dir = Path(__file__).parent.parent / "config" / "skills"
    path = skill_dir / f"{name}.md"
    if path.exists():
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        while lines and lines[0].startswith("#"):
            lines.pop(0)
        return "\n".join(lines).strip()
    return ""


# ═══ Challenge 检测 ═══

def _detect_challenge(truth: ConversationTruth, last_challenge_round: int) -> str | None:
    """检测是否注入 challenge。返回文本或 None。"""
    round_idx = truth.round_idx
    if round_idx - last_challenge_round < CHALLENGE_COOLDOWN:
        return None

    history = truth.action_history

    # 1. 重复操作（同一 target 3+ 次）
    if len(history) >= 3:
        from collections import Counter
        recent = history[-5:]
        sigs = [f"{a['type']}::{a['target']}" for a in recent]
        counter = Counter(sigs)
        most_common, count = counter.most_common(1)[0]
        if count >= 3:
            name, _, target = most_common.partition("::")
            return (
                f"<challenge>\n"
                f"你在最近 {len(recent)} 轮中对相同目标执行了 {count} 次 `{name}`（目标: {target}）。\n"
                f"请评估：换一种方式是否更高效？如果已有足够信息，请直接回复用户。\n"
                f"</challenge>"
            )

    # 2. Plan 缺失（第 3 轮起 + 有 action 历史）
    if round_idx >= 3 and history and not truth.state.pinned_plan:
        plan_skill = _load_skill("plan_protocol")
        if plan_skill:
            return (
                f"<challenge>\n"
                f"你已执行了多步操作但未维护 plan。请按以下格式输出：\n\n"
                f"{plan_skill}\n"
                f"</challenge>"
            )

    # 3. 长时间无回复（10+ 轮）
    if round_idx >= 10 and len(history) >= 10:
        return (
            f"<challenge>\n"
            f"已执行 {round_idx} 轮操作，尚未给用户任何回复。\n"
            f"请评估：你已有的信息是否足够回答用户？如果是，请直接回复。\n"
            f"</challenge>"
        )

    return None


# ═══ 主循环 ═══

async def action_loop_v3(
    orch: Any,
    user_input: str,
    system_prompt: str,
    client: Any,
    file_context: str = "",
) -> dict:
    """基于 ConversationTruth 的 action loop。

    返回 {"final_reply": str, "reason": str, "rounds": int}
    """
    from educe.core.action_executor import parse_actions
    from educe.core.session_env import update_state_from_input, SessionState

    # 初始化 truth
    truth = ConversationTruth(system_prompt)

    # Session env
    if not hasattr(orch, 'session_env') or orch.session_env is None:
        orch.session_env = SessionState()
    update_state_from_input(orch.session_env, user_input)

    # 用户输入
    user_content = user_input
    if file_context:
        user_content = f"{user_input}\n\n{file_context}"
    truth.add_user(user_content)

    # Plan 状态
    current_plan = None
    final_reply = ""
    start_time = time.monotonic()
    last_challenge_round = -999
    exit_reason = "no_action"  # 默认

    for round_idx in range(HARD_ROUND_CAP):
        truth.round_idx = round_idx

        # Wall clock
        elapsed = time.monotonic() - start_time
        if elapsed > WALL_CLOCK_TIMEOUT:
            log.warning("loop_v3 | wall clock timeout at round %d (%.0fs)", round_idx, elapsed)
            exit_reason = "timeout"
            break

        # ── 更新注入 state ──
        truth.state.env = orch.session_env.render() if not orch.session_env.is_empty() else ""

        if current_plan:
            truth.state.pinned_plan = current_plan.to_block()

        if truth.action_history:
            plan_skill = _load_skill("plan_protocol")
            if plan_skill and not truth.state.plan_protocol:
                truth.state.plan_protocol = plan_skill

        if hasattr(orch, 'effects'):
            orch.effects.set_round(round_idx)
            truth.state.situation = orch.effects.situation.render_for_model() or ""

        challenge = _detect_challenge(truth, last_challenge_round)
        if challenge:
            truth.state.challenge = challenge
            last_challenge_round = round_idx
        else:
            truth.state.challenge = ""

        # ── 压缩 ──
        truth.compact()

        # ── 投影 messages（唯一出口）──
        messages = truth.project()

        # ── LLM 调用 ──
        log.info("loop_v3 | round=%d msgs=%d elapsed=%.1fs", round_idx, len(messages), elapsed)
        _llm_t0 = time.time()
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
            log.error("loop_v3 | round %d LLM timeout", round_idx)
            exit_reason = "llm_timeout"
            break
        except Exception as e:
            log.error("loop_v3 | round %d LLM error: %s", round_idx, str(e)[:100])
            exit_reason = "llm_error"
            break

        _llm_ms = (time.time() - _llm_t0) * 1000
        _usage = getattr(client, 'last_usage', None) or {}
        if hasattr(orch, '_slog'):
            orch._slog("llm_call", "llm_response", duration_ms=_llm_ms,
                       data={"round_idx": round_idx,
                             "prompt_tokens": _usage.get("prompt_tokens", 0),
                             "completion_tokens": _usage.get("completion_tokens", 0),
                             "total_tokens": _usage.get("total_tokens", 0)})

        if not raw or not raw.strip():
            log.warning("loop_v3 | round %d empty response", round_idx)
            exit_reason = "empty_response"
            break

        # ── 解析 plan + actions ──
        new_plan = parse_plan(raw)
        if new_plan:
            current_plan = new_plan
        reply_text, actions = parse_actions(raw)

        # ── status=done → 终止 ──
        if current_plan and current_plan.status == "done":
            text = _strip_plan(reply_text or raw)
            if text:
                for i in range(0, len(text), 20):
                    orch._notify_chunk("assistant", text[i:i+20])
                final_reply = text
                if hasattr(orch, 'state'):
                    orch.state.add_ai_reply(text)
            truth.add_agent(raw)
            exit_reason = "done"
            break

        # ── 无 action → 回复用户 ──
        if not actions:
            text = _strip_plan(reply_text or raw)
            if text:
                for i in range(0, len(text), 20):
                    orch._notify_chunk("assistant", text[i:i+20])
                final_reply = text
                if hasattr(orch, 'state'):
                    orch.state.add_ai_reply(text)
            truth.add_agent(raw)
            exit_reason = "no_action"
            break

        # ── 不可逆检查 ──
        from educe.core.irreversibility import is_irreversible
        pending_confirm = [a for a in actions if is_irreversible(a)]
        immediate = [a for a in actions if a not in pending_confirm]

        if pending_confirm:
            import json as _json_cf
            from educe.core.message import Message, MessageType
            confirm_items = [{"type": a.type, "params": a.params, "name": a.name,
                              "display": f"{a.type}: {a.params[:60]}"} for a in pending_confirm]
            orch.context.metadata["_pending_actions"] = confirm_items
            orch.context.metadata["_pending_user_input"] = user_input
            confirm_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                content="__ACTION_CONFIRM__" + _json_cf.dumps(confirm_items, ensure_ascii=False))
            orch._notify(confirm_msg)
            return {"final_reply": "", "reason": "confirm_pending", "rounds": round_idx}

        # ── 执行 actions ──
        truth.add_agent(raw, action_type=immediate[0].type if immediate else "",
                        action_target=immediate[0].params.split("\n")[0][:60] if immediate else "")

        for action in immediate:
            result = await orch._execute_action(action, user_input,
                                               orch.context.metadata.get("_transcript"))
            _emit_action_detail(orch, action, result, round_idx)

            output = result.get("output", "")[:500]
            success = result.get("success", False)

            truth.add_tool_result(
                f"[系统] {'✓' if success else '✗'} {action.type} 结果：{output}",
                success=success, action_type=action.type)

            # cwd 跟踪
            if success and hasattr(orch, 'session_env'):
                if action.type == "shell" and action.params.strip().startswith("cd /"):
                    new_dir = action.params.strip()[3:].strip().rstrip("/")
                    orch.session_env.update_cwd(new_dir, round_idx)
                elif action.type == "read_dir" and action.params.strip().startswith("/"):
                    orch.session_env.pin_path(action.params.strip(), turn_id=round_idx)

            if hasattr(orch, 'effects') and action.type == "shell":
                orch.effects.emit("shell",
                    intent={"cmd": action.params[:60]},
                    outcome={"exit_code": result.get("exit_code", 0)})

        # "说了再做"
        if reply_text:
            clean = _strip_plan(reply_text)
            if clean:
                for i in range(0, len(clean), 20):
                    orch._notify_chunk("assistant", clean[i:i+20])
                if hasattr(orch, 'state'):
                    orch.state.add_ai_reply(clean)

    # ── 保底总结（不写入 truth，避免污染）──
    if not final_reply and truth.round_idx > 0:
        try:
            temp_msgs = truth.project()
            temp_msgs.append({"role": "user", "content": "请基于已有信息直接给出简洁总结回复。"})
            _sum_t0 = time.time()
            summary = await asyncio.wait_for(
                client.chat(messages=temp_msgs, model=orch.config.default_model.model,
                            max_tokens=orch.config.default_model.max_tokens),
                timeout=30)
            _sum_ms = (time.time() - _sum_t0) * 1000
            _sum_usage = getattr(client, 'last_usage', None) or {}
            if hasattr(orch, '_slog'):
                orch._slog("llm_call", "llm_response", duration_ms=_sum_ms,
                           data={"round_idx": truth.round_idx, "summary_call": True,
                                 "prompt_tokens": _sum_usage.get("prompt_tokens", 0),
                                 "completion_tokens": _sum_usage.get("completion_tokens", 0),
                                 "total_tokens": _sum_usage.get("total_tokens", 0)})
            if summary and summary.strip():
                text = _strip_plan(summary.strip())
                if text:
                    for i in range(0, len(text), 20):
                        orch._notify_chunk("assistant", text[i:i+20])
                    final_reply = text
                    if hasattr(orch, 'state'):
                        orch.state.add_ai_reply(text)
        except Exception as e:
            log.warning("loop_v3 | summary call failed: %s", str(e)[:100])

    # ── 写入 conversation（跨轮上下文）──
    if final_reply:
        orch.conversation.add_assistant(final_reply)

    return {
        "final_reply": final_reply,
        "reason": exit_reason,
        "rounds": truth.round_idx,
    }


def _emit_action_detail(orch, action, result, round_idx):
    import json as _json
    try:
        from educe.core.message import Message, MessageType
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
