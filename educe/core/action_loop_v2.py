"""Action Loop V2 — Plan + Challenge + 压缩

核心机制：
1. 模型维护 <plan> 块（自知状态 + status=done 自决停止）
2. Challenge：检测重复/空转，强制模型回应（不可忽略）
3. 三层滑动窗口压缩（hot/warm/frozen）
4. wall_clock 120s 超时兜底
5. Pinned plan 每轮注入
6. 跨轮上下文：plan.findings 写入 conversation
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from typing import Any

from educe.core.plan_parser import parse_plan, _PLAN_RE
from educe.core.loop_context import LoopContext, TurnRecord, PIN_LABEL

log = logging.getLogger("educe.loop_v2")


def _strip_plan(text: str) -> str:
    """从文本中移除 <plan>...</plan> 块，只留给用户看的内容。"""
    return _PLAN_RE.sub("", text).strip()


WALL_CLOCK_TIMEOUT = 120
CHALLENGE_COOLDOWN = 2

# ═══ Skill 加载 ═══

_SKILL_DIR = None

def _load_skill(name: str) -> str:
    """从 educe/config/skills/ 加载可注入的 skill 片段。"""
    global _SKILL_DIR
    if _SKILL_DIR is None:
        from pathlib import Path
        _SKILL_DIR = Path(__file__).parent.parent / "config" / "skills"
    path = _SKILL_DIR / f"{name}.md"
    if path.exists():
        content = path.read_text(encoding="utf-8").strip()
        # 跳过首行注释
        lines = content.splitlines()
        while lines and lines[0].startswith("#"):
            lines.pop(0)
        return "\n".join(lines).strip()
    return ""  # 至少隔 2 轮才能再次 challenge


# ═══ Challenge 检测 ═══

def _detect_challenges(round_idx: int, action_history: list[dict],
                       has_plan: bool, last_challenge_round: int) -> str | None:
    """检测是否应该注入 challenge。返回 challenge 文本或 None。"""
    if round_idx - last_challenge_round < CHALLENGE_COOLDOWN:
        return None

    # 1. 重复操作检测（同一 target 3+ 次）
    if len(action_history) >= 3:
        recent = action_history[-5:]
        sigs = [f"{a['type']}::{a['target']}" for a in recent]
        counter = Counter(sigs)
        most_common, count = counter.most_common(1)[0]
        if count >= 3:
            name, _, target = most_common.partition("::")
            return (
                f"<challenge>\n"
                f"你在最近 {len(recent)} 轮中对相同目标执行了 {count} 次 `{name}`（目标: {target}）。\n"
                f"这似乎没有产生新信息。请在你的 plan 中说明：\n"
                f"- 你在找什么？\n"
                f"- 换一种方式（如 search_in_file 定位关键词）是否更高效？\n"
                f"- 如果已有足够信息，请直接回复用户。\n"
                f"</challenge>"
            )

    # 2. Plan 缺失（第 3 轮起）
    if round_idx >= 3 and not has_plan:
        plan_skill = _load_skill("plan_protocol")
        return (
            "<challenge>\n"
            "你已执行了多步操作但未维护 plan。请按以下格式输出：\n\n"
            f"{plan_skill}\n"
            "</challenge>"
        )

    # 3. 长时间无回复（10+ 轮全在执行）
    if round_idx >= 10 and len(action_history) >= 10:
        return (
            "<challenge>\n"
            f"已执行 {round_idx} 轮操作，尚未给用户任何回复。\n"
            f"请评估：你已有的信息是否足够回答用户的问题？\n"
            f"如果是，请停止操作，直接回复用户（status: done）。\n"
            f"如果不是，请在 plan 中明确说明还缺什么。\n"
            "</challenge>"
        )

    return None


# ═══ 主循环 ═══

async def action_loop_v2(
    orch: Any,
    user_input: str,
    system_prompt: str,
    initial_messages: list[dict],
    client: Any,
    file_context: str = "",
) -> dict:
    """Plan-aware action loop with Challenge mechanism."""
    from educe.core.action_executor import parse_actions
    from educe.core.session_env import update_state_from_input, inject_env, SessionState

    # 确保 orch 有 session_state
    if not hasattr(orch, 'session_env') or orch.session_env is None:
        orch.session_env = SessionState()

    # @path 检测 → 更新 session state
    update_state_from_input(orch.session_env, user_input)

    loop_ctx = LoopContext()
    messages = list(initial_messages)

    # 注入 env（在 system prompt 之后、history 之前）
    messages = inject_env(messages, orch.session_env)

    user_content = user_input
    if file_context:
        user_content = f"{user_input}\n\n{file_context}"
    messages.append({"role": "user", "content": user_content})

    final_reply = ""
    round_idx = 0
    start_time = time.monotonic()
    action_history: list[dict] = []  # {"type": str, "target": str, "round": int}
    last_challenge_round = -999
    HARD_ROUND_CAP = 50

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > WALL_CLOCK_TIMEOUT:
            log.warning("loop_v2 | wall clock timeout at round %d (%.0fs)", round_idx, elapsed)
            break
        if round_idx >= HARD_ROUND_CAP:
            log.warning("loop_v2 | hard round cap reached (%d)", HARD_ROUND_CAP)
            break

        # ── Situation 注入 ──
        if hasattr(orch, 'effects'):
            orch.effects.set_round(round_idx)
            situation_text = orch.effects.situation.render_for_model()
            if situation_text:
                messages.append({"role": "user", "content": situation_text})

        # ── Env 注入（每轮刷新，反映 state 变化）──
        messages = inject_env(messages, orch.session_env)

        # ── Pinned Plan ──
        messages = [m for m in messages if not m.get("content", "").startswith(PIN_LABEL)]
        if loop_ctx.current_plan and round_idx >= 1:
            messages.append({"role": "user", "content": f"{PIN_LABEL}\n{loop_ctx.current_plan.to_block()}"})

        # ── Challenge 注入 ──
        challenge = _detect_challenges(
            round_idx, action_history,
            has_plan=loop_ctx.current_plan is not None,
            last_challenge_round=last_challenge_round,
        )
        if challenge:
            messages.append({"role": "user", "content": challenge})
            last_challenge_round = round_idx
            log.info("loop_v2 | round %d challenge injected", round_idx)

        # ── 压缩：messages 滑动窗口（防止 token 爆炸）──
        loop_ctx.compress_if_needed()
        # 保留 system(前2条) + 最近 20 条 messages
        MAX_MESSAGES = 22
        if len(messages) > MAX_MESSAGES:
            # 保留前 2 条（system + env）和最后 20 条
            messages = messages[:2] + messages[-(MAX_MESSAGES - 2):]

        # ── LLM 调用 ──
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

        # ── 解析 ──
        new_plan = parse_plan(raw)
        loop_ctx.update_plan(new_plan)
        reply_text, actions = parse_actions(raw)

        # ── status=done → 终止 ──
        if loop_ctx.is_done():
            text = _strip_plan(reply_text or raw)
            if text:
                for i in range(0, len(text), 20):
                    orch._notify_chunk("assistant", text[i:i+20])
            final_reply = text or ""
            if hasattr(orch, 'state') and text:
                orch.state.add_ai_reply(text)
            break

        # ── 无 action → 回复用户 → 终止 ──
        if not actions:
            text = _strip_plan(reply_text or raw)
            if text:
                for i in range(0, len(text), 20):
                    orch._notify_chunk("assistant", text[i:i+20])
            final_reply = text or ""
            if hasattr(orch, 'state') and text:
                orch.state.add_ai_reply(text)
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
        messages.append({"role": "assistant", "content": raw})

        for action in immediate:
            result = await orch._execute_action(action, user_input,
                                               orch.context.metadata.get("_transcript"))
            _emit_action_detail(orch, action, result, round_idx)

            output = result.get("output", "")[:500]
            success = result.get("success", False)
            messages.append({"role": "user", "content":
                f"[系统] {'✓' if success else '✗'} {action.type} 结果：{output}"})

            # 记录 action 历史（用于 challenge 检测）
            target = action.params.split("\n")[0][:60] if action.params else ""
            action_history.append({"type": action.type, "target": target, "round": round_idx})

            # cwd 跟踪：只信任绝对路径
            if success and hasattr(orch, 'session_env'):
                if action.type == "shell" and action.params.strip().startswith("cd "):
                    new_dir = action.params.strip()[3:].strip().rstrip("/")
                    if new_dir.startswith("/"):  # 只信任绝对路径
                        orch.session_env.update_cwd(new_dir, round_idx)
                elif action.type == "read_dir" and action.params.strip().startswith("/"):
                    orch.session_env.pin_path(action.params.strip(), turn_id=round_idx)

            loop_ctx.add_turn(TurnRecord(
                round_idx=round_idx,
                assistant_raw=raw,
                action_type=action.type,
                action_params=action.params[:100],
                result_output=output,
                success=success,
            ))

            if hasattr(orch, 'effects') and action.type == "shell":
                orch.effects.emit("shell",
                    intent={"cmd": action.params[:60]},
                    outcome={"exit_code": result.get("exit_code", 0)})

        # ── "说了再做" ──
        if reply_text:
            clean_reply = _strip_plan(reply_text)
            if clean_reply:
                for i in range(0, len(clean_reply), 20):
                    orch._notify_chunk("assistant", clean_reply[i:i+20])
                if hasattr(orch, 'state'):
                    orch.state.add_ai_reply(clean_reply)

        round_idx += 1

    # ── 保底总结（超时退出时） ──
    if not final_reply and round_idx > 0:
        try:
            messages.append({"role": "user", "content":
                "[系统] 请基于已有信息直接给出简洁总结回复。"})
            summary = await asyncio.wait_for(
                client.chat(messages=messages, model=orch.config.default_model.model,
                            max_tokens=orch.config.default_model.max_tokens),
                timeout=30)
            if summary and summary.strip():
                text = _strip_plan(summary.strip())
                if text:
                    for i in range(0, len(text), 20):
                        orch._notify_chunk("assistant", text[i:i+20])
                    final_reply = text
                    if hasattr(orch, 'state'):
                        orch.state.add_ai_reply(text)
        except Exception as e:
            log.warning("loop_v2 | summary call failed: %s", str(e)[:100])

    # ── 写入 conversation（确保跨轮上下文不丢失关键信息） ──
    # 核心：下一轮模型必须能看到"上次操作了什么路径/发现了什么"
    context_parts = []

    # 1. 用户原始请求（含路径）
    context_parts.append(f"用户请求: {user_input[:100]}")

    # 2. Plan findings（如果有）
    if loop_ctx.current_plan and loop_ctx.current_plan.findings:
        context_parts.append("发现: " + "; ".join(loop_ctx.current_plan.findings[:8]))

    # 3. 关键操作路径（从 action history 提取唯一路径）
    paths_seen = []
    for turn in loop_ctx.hot:
        if turn.action_type in ("read_dir", "read_file", "shell") and turn.action_params:
            path = turn.action_params.split("\n")[0][:80]
            if path not in paths_seen:
                paths_seen.append(path)
    if paths_seen:
        context_parts.append("操作路径: " + ", ".join(paths_seen[:5]))

    if context_parts:
        orch.conversation.add_assistant("[上轮摘要] " + " | ".join(context_parts))

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
