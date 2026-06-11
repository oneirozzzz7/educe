"""
DeepForge Orchestrator v2
3-Agent架构：Builder + Tester + Planner
Orchestrator做路由和循环控制，不是Agent
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Callable

log = logging.getLogger("deepforge.orchestrator")

from deepforge.core.activity_log import log_activity

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from deepforge.core.agent import BaseAgent
from deepforge.core.config import DeepForgeConfig
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.core.observer import Observer
from deepforge.core.task_store import TaskStore
from deepforge.core.event_bus import EventBus
from deepforge.core.knowledge import LayeredCache

console = Console()


class Orchestrator:
    def __init__(self, config: DeepForgeConfig, max_iterations: int = 3):
        self.config = config
        self.agents: dict[str, BaseAgent] = {}
        self.context = WorkContext()
        self.max_iterations = max_iterations
        self.observer = Observer()
        self.task_store = TaskStore()
        self.bus = EventBus()
        self.knowledge = LayeredCache()

        from deepforge.core.unified_store import UnifiedKnowledgeStore
        self.unified_store = None
        try:
            self.unified_store = UnifiedKnowledgeStore(Path(".deepforge/unified"))
        except Exception:
            pass

        from deepforge.core.session_store import SessionStore
        self.session_store = SessionStore()

        from deepforge.core.conversation import ConversationManager
        self.conversation = ConversationManager(knowledge=self.knowledge)

        from deepforge.core.quality_tracker import QualityTracker
        self.quality_tracker = QualityTracker()

        self.domain_engine = None
        try:
            from deepforge.core.domain_engine import DomainEngine
            self.domain_engine = DomainEngine(knowledge=self.knowledge)
        except Exception:
            pass

        self.activation_engine = None
        try:
            from deepforge.core.activation_engine import ActivationEngine
            self.activation_engine = ActivationEngine(knowledge=self.knowledge, domain_engine=self.domain_engine)
        except Exception:
            pass

        self.context_analyzer = None
        try:
            from deepforge.core.context_analyzer import ContextAnalyzer
            self.context_analyzer = ContextAnalyzer()
        except Exception:
            pass

        self.distiller = None
        try:
            from deepforge.core.knowledge_distiller import KnowledgeDistiller
            self.distiller = KnowledgeDistiller(self.knowledge)
        except Exception:
            pass

        self.profile_manager = None
        try:
            from deepforge.core.user_profile import UserProfileManager
            self.profile_manager = UserProfileManager()
        except Exception:
            pass

        self.credibility = None
        try:
            from deepforge.core.credibility_engine import CredibilityEngine
            self.credibility = CredibilityEngine(
                knowledge=self.knowledge, quality_tracker=self.quality_tracker)
        except Exception:
            pass

        self.self_evolver = None

        self._on_message: list[Callable] = []
        self._on_chunk: list[Callable] = []

    def register(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent

    def on_message(self, callback: Callable) -> None:
        self._on_message.append(callback)

    def on_chunk(self, callback: Callable) -> None:
        self._on_chunk.append(callback)

    def _notify(self, msg: Message) -> None:
        for cb in self._on_message:
            cb(msg)

    def _notify_chunk(self, agent_name: str, chunk: str) -> None:
        for cb in self._on_chunk:
            cb(agent_name, chunk)

    def _display(self, msg: Message) -> None:
        icon = {"builder": "💻", "tester": "🧪", "planner": "📋", "assistant": "💬"}.get(msg.sender, "🤖")
        console.print(Panel(Markdown(msg.content[:500]), title=f"{icon} {msg.sender}", border_style="cyan", padding=(0, 1)))

    # ═══════════════════════════════════════
    #  唯一入口
    # ═══════════════════════════════════════

    async def run(self, user_input: str, file_content: str | None = None) -> WorkContext:
        self.context.user_request = user_input
        _sid = self.context.metadata.get("session_id", "")
        log_activity(_sid, "user_input", input=user_input[:200],
                     has_file=bool(file_content))

        # ═══ 反馈回填（检测用户对上一轮回答的信号）═══
        prev_assistant = ""
        if self.conversation.turns:
            for t in reversed(self.conversation.turns):
                if t.role == "assistant":
                    prev_assistant = t.content
                    break
        if prev_assistant:
            signal, weight = self.quality_tracker.detect_user_signal(user_input, prev_assistant)
            self.context.metadata["_last_user_signal"] = signal
            self.context.metadata["_last_signal_weight"] = weight
            if self.unified_store and signal != "neutral":
                self.unified_store.record_signal({
                    "type": "user_feedback",
                    "session_id": _sid,
                    "signal": signal,
                    "weight": weight,
                })
            prev_recalled = self.context.metadata.get("_recalled_knowledge_ids", [])
            if prev_recalled and self.unified_store:
                is_positive = signal in ("grateful", "engaged")
                is_negative = signal in ("error", "unsatisfied")
                if is_positive or is_negative:
                    for eid in prev_recalled:
                        self.unified_store.record_usage(eid, success=is_positive)
                    log_activity(_sid, "knowledge_feedback",
                                signal=signal, ids=prev_recalled,
                                success=is_positive)

        # ═══ 清除上一轮状态 ═══
        self.context.metadata.pop("_recalled_knowledge_ids", None)
        self.context.metadata.pop("domain_knowledge", None)

        self.conversation.add_user(user_input, file_content)
        if hasattr(self, 'state'):
            self.state.add_user_input(user_input)

        if file_content:
            self.context.metadata["uploaded_files_text"] = file_content
        else:
            active_file = self.conversation.get_active_file_context(user_input)
            if active_file:
                self.context.metadata["uploaded_files_text"] = active_file
            else:
                self.context.metadata.pop("uploaded_files_text", None)

        # ═══ 如果有待确认的 action（用户确认/补充/取消）═══
        pending = self.context.metadata.get("_pending_actions")
        if pending:
            return await self._handle_action_confirm(user_input, pending)

        # ═══ 如果有用户决策回来——直接走构建 ═══
        if self.context.metadata.get("_user_decisions"):
            self.context.metadata["expert_name"] = "编程专家"
            transcript = self.context.metadata.get("_transcript")
            if transcript:
                decisions = self.context.metadata["_user_decisions"]
                choices = ", ".join(d.get("choice", "") for d in decisions)
                transcript.add("plan", "user", "确认选择: {}".format(choices[:100]))
            result = await self._run_build(user_input)
            self.context.metadata.pop("_user_decisions", None)
            self.context.metadata.pop("_pending_request", None)
            return result

        # ═══ Transcript 设置 ═══
        from deepforge.core.transcript import TaskTranscript
        transcript = self.context.metadata.get("_transcript")
        if transcript:
            transcript.user_request = user_input
        else:
            transcript = TaskTranscript(user_input)

        def push_transcript_event(evt: dict):
            import json as _json
            evt_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                content="__TOOL_EVENT__" + _json.dumps(evt, ensure_ascii=False))
            self._notify(evt_msg)
            if hasattr(self, 'state'):
                self.state.add_event("transcript", **{k: v for k, v in evt.items() if k != "event"})
        transcript.on_update = push_transcript_event
        self.context.metadata["_transcript"] = transcript
        if hasattr(self, 'state'):
            self.context.metadata["_session_state"] = self.state
        return await self._action_loop(user_input, transcript)

    async def _action_loop(self, user_input: str, transcript) -> WorkContext:
        """核心行为循环：模型自由决策，框架执行。"""
        from deepforge.core.action_executor import parse_actions
        from deepforge.core.context_manager import build_context, SessionMemory

        client = self._get_client()
        if not client:
            msg = Message(type=MessageType.RESULT, sender="assistant",
                         receiver="user", content="请先配置模型。")
            self.context.add_message(msg)
            self._notify(msg)
            return self.context

        _sid = self.context.metadata.get("session_id", "")

        # 构建 context（索引式知识呈现 + 作用域隔离）
        seed = ""
        if self.unified_store:
            seed = self.unified_store.get_seed_text("build", "general")

        catalog = []
        if self.unified_store:
            catalog = self.unified_store._catalog

        # session 临时记忆
        session_memory = self.context.metadata.get("_session_memory")
        if not session_memory:
            session_memory = SessionMemory()
            self.context.metadata["_session_memory"] = session_memory

        # 文件上下文加入 session 记忆
        file_context = self.context.metadata.get("uploaded_files_text", "")
        if file_context:
            session_memory.add(f"用户上传了文件（{len(file_context)}字符）")

        system = build_context(
            session_memory=session_memory,
            catalog=catalog,
            seed=seed,
        )

        # 构建对话历史
        history = self.conversation.get_history_for_llm()
        cleaned = []
        for h in history:
            content = h.get("content", "")
            if len(content) > 1500:
                cleaned.append({"role": h["role"], "content": content[:300] + "\n...(截断)"})
            else:
                cleaned.append(h)
        history = cleaned[-6:]

        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})

        max_rounds = 5
        final_reply = ""

        for round_idx in range(max_rounds):
            # 模型调用（action 轮次用非流式，避免标签被流式推送到前端）
            try:
                raw = await client.chat(
                    messages=messages,
                    model=self.config.default_model.model,
                    max_tokens=self.config.default_model.max_tokens,
                )
            except Exception as e:
                log.error("_action_loop | model call failed: %s", str(e)[:100])
                raw = ""

            # 解析 action
            reply_text, actions = parse_actions(raw)
            log_activity(_sid, "model_output",
                        round=round_idx,
                        has_actions=len(actions),
                        action_types=[a.type for a in actions],
                        reply_preview=reply_text[:80])

            if not actions:
                # 无 action = 纯回复，流式推送给用户，循环结束
                for i in range(0, len(raw), 20):
                    self._notify_chunk("assistant", raw[i:i+20])
                final_reply = raw
                if hasattr(self, 'state'):
                    self.state.add_ai_reply(raw)
                break

            # 需要用户确认的 action 类型
            needs_confirm = {"memorize", "build"}

            # 检查是否有需要确认的 action
            pending_actions = [a for a in actions if a.type in needs_confirm]
            immediate_actions = [a for a in actions if a.type not in needs_confirm]

            # 立即执行不需要确认的（recall、lookup_tools、use_tool）
            if immediate_actions:
                messages.append({"role": "assistant", "content": raw})
            for action in immediate_actions:
                result = await self._execute_action(action, user_input, transcript)
                log_activity(_sid, "action_executed",
                            type=action.type,
                            success=result.get("success", False),
                            output_preview=result.get("output", "")[:80])
                if hasattr(self, 'state'):
                    self.state.add_action_executed(
                        action.type, result.get("output", ""), result.get("success", False))
                messages.append({"role": "user", "content":
                    f"[系统] 操作 {action.type} 执行结果：{result.get('output', '')[:500]}"})

            # immediate action 伴随的文字推送给用户
            if immediate_actions and reply_text and not pending_actions:
                for i in range(0, len(reply_text), 20):
                    self._notify_chunk("assistant", reply_text[i:i+20])
                self.conversation.add_assistant(reply_text)
                if hasattr(self, 'state'):
                    self.state.add_ai_reply(reply_text)

            # 需要确认的 action → 暂存，发确认请求给前端，返回等待
            if pending_actions:
                import json as _json

                # reply_text 写入 conversation（模型记得自己说了什么）
                if reply_text:
                    self.conversation.add_assistant(reply_text)

                # 构造待确认的 action 列表
                confirm_items = []
                for a in pending_actions:
                    item = {"type": a.type, "params": a.params, "name": a.name}
                    if a.type == "memorize":
                        try:
                            parsed = _json.loads(a.params)
                            op = parsed.get("op", "add")
                            if op == "add":
                                item["display"] = f"记住：{parsed.get('content', parsed.get('value', a.params[:60]))}"
                            elif op == "delete":
                                item["display"] = f"删除记忆：{parsed.get('keyword', parsed.get('key', ''))}"
                            else:
                                item["display"] = f"记忆操作：{op}"
                        except Exception:
                            item["display"] = f"记忆操作：{a.params[:60]}"
                    elif a.type == "build":
                        item["display"] = f"构建：{a.params[:100]}"
                    confirm_items.append(item)

                # 暂存到 context，等用户确认
                self.context.metadata["_pending_actions"] = confirm_items
                self.context.metadata["_pending_user_input"] = user_input

                # 发送确认请求到前端
                confirm_msg = Message(
                    type=MessageType.SYSTEM, sender="system", receiver="user",
                    content="__ACTION_CONFIRM__" + _json.dumps(confirm_items, ensure_ascii=False))
                self._notify(confirm_msg)

                if hasattr(self, 'state'):
                    if reply_text:
                        self.state.add_ai_reply(reply_text)
                    self.state.add_action_confirm(confirm_items)

                log_activity(_sid, "action_confirm_request",
                            actions=[i["display"] for i in confirm_items])
                return self.context

        if final_reply:
            self.conversation.add_assistant(final_reply)

        return self.context

    async def _execute_action(self, action, user_input: str, transcript) -> dict:
        """执行单个 action，返回结果 dict。"""
        from deepforge.core.action_executor import ParsedAction
        import json as _json
        _sid = self.context.metadata.get("session_id", "")

        if action.type == "memorize":
            result = await self._exec_memorize(action, _sid)
            # memorize 成功后更新 session 记忆
            if result.get("success") and "已记住" in result.get("output", ""):
                session_memory = self.context.metadata.get("_session_memory")
                if session_memory:
                    session_memory.add(result["output"])
            return result

        elif action.type == "build":
            self.context.metadata["expert_name"] = "编程专家"
            transcript.current_phase = "build"
            transcript.add("analyze", "system", "任务类型: BUILD")
            await self._run_build(user_input)
            return {"success": True, "output": "构建完成"}

        elif action.type == "recall":
            return await self._exec_recall(action, _sid)

        elif action.type == "lookup_tools":
            tools = self._get_tool_descriptions()
            return {"success": True, "output": f"可用工具：\n{tools}"}

        elif action.type == "use_tool":
            return await self._exec_use_tool(action)

        else:
            return {"success": False, "output": f"未知操作: {action.type}"}

    async def _exec_recall(self, action, session_id: str) -> dict:
        """检索知识系统，返回具体内容"""
        if not self.unified_store:
            return {"success": False, "output": "知识系统未初始化"}

        keyword = action.params.strip()
        # 从 catalog 中搜索匹配的条目
        results = []
        for entry_data in self.unified_store._catalog:
            preview = entry_data.get("preview", "")
            domain = entry_data.get("domain", "")
            category = entry_data.get("category", "")
            if (keyword in preview or keyword in domain or keyword in category):
                entry = self.unified_store.get_entry(entry_data["id"])
                if entry:
                    results.append(entry.content.body)

        if not results:
            return {"success": True, "output": f"未找到与「{keyword}」相关的记忆。"}

        # 记录 recalled IDs 用于反馈闭环
        recalled_ids = [e["id"] for e in self.unified_store._catalog
                       if keyword in e.get("preview", "") or keyword in e.get("domain", "")]
        self.context.metadata["_recalled_knowledge_ids"] = recalled_ids
        log_activity(session_id, "knowledge_recall",
                    count=len(results), ids=recalled_ids,
                    keyword=keyword)

        lines = "\n".join(f"- {r}" for r in results[:5])
        return {"success": True, "output": f"找到 {len(results)} 条相关记忆：\n{lines}"}

    async def _exec_memorize(self, action, session_id: str) -> dict:
        """执行记忆操作"""
        import json as _json
        if not self.unified_store:
            return {"success": False, "output": "知识系统未初始化"}
        try:
            parsed = _json.loads(action.params)
        except Exception:
            parsed = {"op": "add", "content": action.params}

        op = parsed.get("op", "add")
        log_activity(session_id, "memorize_op", op=op, parsed=parsed)

        if op == "list":
            entries = self.unified_store._catalog
            if not entries:
                return {"success": True, "output": "当前没有已记录的知识。"}
            lines = [f"- {e['preview']}" for e in entries[:15]]
            return {"success": True, "output": f"已记录 {len(entries)} 条知识：\n" + "\n".join(lines)}

        elif op == "delete":
            keyword = parsed.get("keyword", parsed.get("key", ""))
            for e in list(self.unified_store._catalog):
                if keyword and keyword in e["preview"]:
                    path = self.unified_store.entries_dir / f"{e['id']}.json"
                    if path.exists():
                        path.unlink()
                    self.unified_store._catalog.remove(e)
                    self.unified_store._save_catalog()
                    self.unified_store._invalidate_compiled()
                    return {"success": True, "output": f"已删除包含「{keyword}」的知识。"}
            return {"success": False, "output": f"未找到包含「{keyword}」的知识。"}

        else:
            content = parsed.get("content", parsed.get("value", action.params))
            if isinstance(content, dict):
                content = str(content)
            category = parsed.get("category", "insight")
            domain = parsed.get("domain", "general")
            self.unified_store.add(
                content=content, source="user", maturity="pattern",
                scope="project", category=category, domain=domain,
                session_id=session_id)
            return {"success": True, "output": f"已记住：{content}"}

    async def _exec_use_tool(self, action) -> dict:
        """执行外部工具调用"""
        return {"success": False, "output": f"工具 {action.name} 尚未注册"}

    async def _handle_action_confirm(self, user_input: str, pending: list) -> "WorkContext":
        """处理用户对待确认 action 的回应（确认/补充/取消）"""
        from deepforge.core.action_executor import ParsedAction
        import json as _json
        _sid = self.context.metadata.get("session_id", "")
        original_input = self.context.metadata.get("_pending_user_input", "")

        # 让模型判断用户的回应是确认、补充还是取消
        client = self._get_client()
        if not client:
            self.context.metadata.pop("_pending_actions", None)
            return self.context

        pending_desc = "\n".join(f"- {p['display']}" for p in pending)
        result = await client.chat(
            messages=[
                {"role": "system", "content": (
                    "用户之前的操作需要确认。待执行操作：\n" + pending_desc + "\n\n"
                    "用户刚才的回应是什么意思？输出JSON：\n"
                    "{\"decision\": \"confirm\" | \"cancel\" | \"revise\", \"note\": \"用户补充的内容\"}\n"
                    "- confirm: 用户同意执行（如'好的'、'确认'、'可以'、'就这样'）\n"
                    "- cancel: 用户取消（如'算了'、'不要了'、'取消'）\n"
                    "- revise: 用户补充或修改了需求（如'再加个...'、'改成...'、其他具体内容）\n"
                    "只输出JSON。"
                )},
                {"role": "user", "content": user_input},
            ],
            model=self.config.default_model.model,
            max_tokens=100, temperature=0.0,
        )

        try:
            parsed = _json.loads(result.strip().strip("```json").strip("```"))
        except Exception:
            parsed = {"decision": "confirm", "note": ""}

        decision = parsed.get("decision", "confirm")
        note = parsed.get("note", "")

        log_activity(_sid, "action_confirm_response",
                    decision=decision, note=note[:80])
        if hasattr(self, 'state'):
            self.state.add_user_confirm(decision, note)

        if decision == "cancel":
            self.context.metadata.pop("_pending_actions", None)
            self.context.metadata.pop("_pending_user_input", None)
            self.conversation.add_assistant("好的，已取消。")
            if hasattr(self, 'state'):
                self.state.add_ai_reply("好的，已取消。")
            return self.context

        elif decision == "revise":
            # 用户补充了内容 → 清除 pending，用新的完整需求重新走 action loop
            self.context.metadata.pop("_pending_actions", None)
            self.context.metadata.pop("_pending_user_input", None)
            # 把原始需求 + 补充内容合并重新处理
            revised_input = f"{original_input}。补充：{user_input}"
            # 重新走 transcript + action loop
            from deepforge.core.transcript import TaskTranscript
            transcript = self.context.metadata.get("_transcript")
            if not transcript:
                transcript = TaskTranscript(revised_input)
                self.context.metadata["_transcript"] = transcript
            return await self._action_loop(revised_input, transcript)

        else:
            # confirm → 执行所有 pending actions
            self.context.metadata.pop("_pending_actions", None)
            self.context.metadata.pop("_pending_user_input", None)

            transcript = self.context.metadata.get("_transcript")
            if not transcript:
                from deepforge.core.transcript import TaskTranscript
                transcript = TaskTranscript(original_input)
                self.context.metadata["_transcript"] = transcript

            # 先执行非 build 的 action，再执行 build（确保 memorize 不被跳过）
            non_build = [p for p in pending if p["type"] != "build"]
            build_actions = [p for p in pending if p["type"] == "build"]

            for p in non_build:
                action = ParsedAction(type=p["type"], params=p["params"], name=p.get("name", ""))
                result = await self._execute_action(action, original_input, transcript)
                log_activity(_sid, "action_executed",
                            type=action.type,
                            success=result.get("success", False),
                            output_preview=result.get("output", "")[:80])
                if hasattr(self, 'state'):
                    self.state.add_action_executed(
                        action.type, result.get("output", ""), result.get("success", False))
                if result.get("output"):
                    for i in range(0, len(result["output"]), 20):
                        self._notify_chunk("assistant", result["output"][i:i+20])
                    self.conversation.add_assistant(result["output"])

            for p in build_actions:
                action = ParsedAction(type=p["type"], params=p["params"], name=p.get("name", ""))
                result = await self._execute_action(action, original_input, transcript)
                log_activity(_sid, "action_executed",
                            type=action.type,
                            success=result.get("success", False),
                            output_preview=result.get("output", "")[:80])
                if hasattr(self, 'state'):
                    self.state.add_action_executed(
                        action.type, result.get("output", ""), result.get("success", False))
                return self.context

            return self.context

    def _get_tool_descriptions(self) -> str:
        """返回当前可用工具的描述"""
        return "暂无外部工具注册。你可以使用内置能力：记忆、构建。"

    # ═══════════════════════════════════════
    #  Builder → Tester → 循环（优化版）
    # ═══════════════════════════════════════

    async def _run_build(self, user_input: str) -> WorkContext:
        pipeline_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user", content="__PIPELINE_START__")
        self._notify(pipeline_msg)

        # 注入统一知识系统到 context，供 builder 使用
        if self.unified_store:
            self.context.metadata["_unified_store"] = self.unified_store

        # 记录 build 开始事件
        if hasattr(self, 'state'):
            self.state.add_build_start()

        # 知识 recall（在 build 确认后执行，不干扰 _decide 意图判断）
        _sid = self.context.metadata.get("session_id", "")
        client = self._get_client()
        if client and self.unified_store:
            recalled = await self.unified_store.recall(
                user_input,
                lambda msgs: client.chat(
                    messages=msgs,
                    model=self.config.default_model.model,
                    max_tokens=50, temperature=0.0),
            )
            if recalled:
                existing = self.context.metadata.get("domain_knowledge", "")
                self.context.metadata["domain_knowledge"] = (
                    existing + "\n## 相关知识\n" + "\n".join(
                        f"- {e.content.body}" for e in recalled))
                self.context.metadata["_recalled_knowledge_ids"] = [
                    e.id for e in recalled]
                self.context.metadata["_recalled_knowledge_summary"] = "、".join(
                    e.content.body[:30] for e in recalled[:3])
                log_activity(_sid, "knowledge_recall",
                            count=len(recalled),
                            ids=[e.id for e in recalled],
                            previews=[e.preview for e in recalled])
                # transcript 记录（此时 transcript 已存在）
                transcript = self.context.metadata.get("_transcript")
                if transcript:
                    transcript.add("analyze", "system",
                        f"应用已有知识：{self.context.metadata['_recalled_knowledge_summary']}")

        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        # ═══ 0. 检测是否是追问迭代（已有代码，用户要求修改）═══
        has_prev_code = bool(self.context.artifacts.get("code_files"))
        prev_code_context = ""
        if has_prev_code:
            from pathlib import Path
            code_files = self.context.artifacts.get("code_files", [])
            parts = []
            for fp in code_files[:3]:
                p = Path(fp)
                if p.exists():
                    parts.append("```filepath:{}\n{}\n```".format(p.name, p.read_text(encoding="utf-8", errors="ignore")[:8000]))
            if parts:
                prev_code_context = "\n\n".join(parts)

        # ═══ 0b. 评估复杂度（迭代修改视为 simple）═══
        if prev_code_context:
            complexity = "simple"
        elif self.context.metadata.get("_task_complexity"):
            complexity = self.context.metadata["_task_complexity"]
        else:
            complexity = await self._assess_complexity(user_input)
        self.context.metadata["_task_complexity"] = complexity

        # ═══ A. 生成需求清单（修改场景跳过，只对新构建有用）═══
        checklist = []
        if not prev_code_context:
            try:
                from deepforge.core.checklist_judge import generate_checklist
                from deepforge.models.router import ModelClient
                client = ModelClient(api_key=self.config.default_model.api_key,
                                    base_url=self.config.default_model.base_url)
                checklist = await generate_checklist(client, self.config.default_model.model, user_input)
            except Exception:
                pass

        # ═══ B. 把 checklist 注入 builder prompt ═══
        build_input = user_input
        if prev_code_context:
            build_input = (
                f"用户要求修改已有代码：{user_input}\n\n"
                f"【当前代码】\n{prev_code_context}\n\n"
                f"请在现有代码基础上进行修改，输出修改后的完整文件。"
            )
        elif checklist:
            checklist_text = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(checklist))
            build_input = (
                f"{user_input}\n\n"
                f"【核心功能要求（必须全部实现）】\n{checklist_text}\n\n"
                f"请逐项实现以上所有功能，确保每项都能正常工作。"
            )

        # ═══ 执行构建 ═══
        await self._run_agent("builder", build_input, "user", timeout=900)

        if self.context.metadata.get("_pending_decisions"):
            return self.context

        # ═══ C. Checklist 验收（StepBuilder 已有内置验证，跳过）═══
        has_output = bool(self.context.artifacts.get("code_files"))
        if has_output and checklist and complexity != "complex":
            try:
                from deepforge.core.checklist_judge import verify_checklist
                code_output = self.context.artifacts.get("engineer_output", "")
                if len(code_output) < 100:
                    # Read actual files for verification
                    from pathlib import Path
                    code_files = self.context.artifacts.get("code_files", [])
                    parts = []
                    for fp in code_files[:3]:
                        p = Path(fp)
                        if p.exists():
                            parts.append(p.read_text(encoding="utf-8", errors="ignore")[:5000])
                    code_output = "\n".join(parts)

                covered = await verify_checklist(client, self.config.default_model.model, checklist, code_output)
                coverage = sum(covered) / len(covered) if covered else 1.0

                # ═══ D. 不通过则修复 ═══
                if coverage < 0.8 and covered:
                    missing = [checklist[i] for i, c in enumerate(covered) if not c]
                    if missing:
                        fix_request = (
                            f"当前代码缺少以下功能，请补充实现：\n"
                            + "\n".join(f"- {item}" for item in missing)
                            + "\n\n请在现有代码基础上添加缺失功能。"
                        )
                        # 通知前端正在修复
                        progress_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                                              content="__BUILD_PROGRESS__验收发现缺失功能，修复中...")
                        self._notify(progress_msg)
                        await self._run_agent("builder", fix_request, "system", timeout=300)
            except Exception:
                pass

        has_output = bool(self.context.artifacts.get("code_files"))
        self.observer.finish_task(success=has_output, project_type=self.context.artifacts.get("project_type", ""),
                                 file_count=len(self.context.artifacts.get("code_files", [])))
        _sid = self.context.metadata.get("session_id", "")
        log_activity(_sid, "build_complete",
                    success=has_output,
                    files=len(self.context.artifacts.get("code_files", [])),
                    complexity=self.context.metadata.get("_task_complexity", "?"))

        # 记录 build 完成事件
        if hasattr(self, 'state'):
            code_files = self.context.artifacts.get("code_files", [])
            self.state.add_build_complete(code_files, success=has_output)

        # 采集 SessionSignal 到统一知识系统
        if self.unified_store:
            import time as _t
            transcript = self.context.metadata.get("_transcript")
            phases = {}
            if transcript:
                for e in transcript.entries:
                    if e.elapsed and e.phase:
                        phases[e.phase] = phases.get(e.phase, 0) + e.elapsed

            recalled_ids = self.context.metadata.get("_recalled_knowledge_ids", [])

            self.unified_store.record_signal({
                "type": "build",
                "session_id": self.context.metadata.get("session_id", ""),
                "request": {
                    "user_input": user_input[:200],
                    "task_type": "build",
                    "complexity": self.context.metadata.get("_task_complexity", "unknown"),
                },
                "execution": {
                    "duration_seconds": round(sum(phases.values()), 1),
                    "phases": phases,
                    "iterations": self.context.artifacts.get("version", 1),
                    "file_count": len(self.context.artifacts.get("code_files", [])),
                    "model": self.config.default_model.model,
                },
                "signals": {
                    "success": has_output,
                    "user_signal": "pending",
                },
                "seeds_used": {
                    "build_seed_id": "seed_build_general",
                },
                "knowledge_used": recalled_ids,
            })

            # 构建成功后：让模型判断是否有可提炼的经验写入知识系统
            if has_output:
                asyncio.create_task(
                    self._maybe_extract_knowledge(user_input, recalled_ids))

        # Session级保存
        session_id = self.context.metadata.get("session_id", "")
        if session_id:
            # Session store only saves a reference — actual files live on disk
            code_files = self.context.artifacts.get("code_files", [])
            file_names = [f.split("/")[-1] for f in code_files]
            # Persist transcript entries for history replay
            transcript = self.context.metadata.get("_transcript")
            transcript_data = None
            if transcript:
                transcript_data = [
                    {"phase": e.phase, "role": e.role, "content": e.content, "elapsed": e.elapsed}
                    for e in transcript.entries
                ]
            self.session_store.append_turn(
                session_id, user_input, ",".join(file_names),
                turn_type="code",
                domain="tech",
                metadata={"transcript": transcript_data} if transcript_data else None,
            )

        # 给conversation加完成记录（简短摘要，不是完整代码）
        code_files = self.context.artifacts.get("code_files", [])
        if code_files:
            filenames = [f.split("/")[-1] for f in code_files]
            summary = "[已完成代码生成] 文件：{}".format(", ".join(filenames))
        else:
            summary = "[代码任务未能完成]"
        self.conversation.add_assistant(summary, domain="tech")
        if hasattr(self, 'state'):
            self.state.add_ai_reply(summary)
            asyncio.create_task(self._evolve_from_result())

        if not has_output:
            fail_msg = Message(type=MessageType.RESULT, sender="system", receiver="user",
                              content="未能生成可用的产出物，请更具体描述需求。")
            self.context.add_message(fail_msg)
            self._notify(fail_msg)

        self.context.metadata.pop("_skip_analysis", None)
        self.context.metadata.pop("_pending_request", None)
        return self.context

    async def _quick_tool_check(self) -> bool:
        """轻量级工具检查——秒级验证，不调LLM"""
        from deepforge.core.tools import RunHTMLTool, RunPythonTool
        code_files = self.context.artifacts.get("code_files", [])
        for filepath in code_files:
            if filepath.endswith(".html"):
                tool = RunHTMLTool()
                result = await tool.execute({"path": filepath})
                if "问题" in result or "错误" in result:
                    return False
            elif filepath.endswith(".py"):
                tool = RunPythonTool()
                result = await tool.execute({"path": filepath})
                if "失败" in result or "错误" in result:
                    return False
        return True

    # ═══════════════════════════════════════
    #  修改已有产出物
    # ═══════════════════════════════════════

    async def _run_modify(self, user_input: str) -> WorkContext:
        prev = self.context.artifacts.get("engineer_output", "")
        await self._run_agent("builder",
            f"用户要求修改：{user_input}\n\n当前代码：\n{prev[:4000]}\n\n输出修改后的完整文件。",
            "user", timeout=180)
        return self.context

    # ═══════════════════════════════════════
    #  决策（模型自己判断）
    # ═══════════════════════════════════════

    async def _decide(self, user_input: str) -> dict:
        """深度意图理解——让模型思考用户真正想要什么，不做关键词匹配。"""
        cs = getattr(self, 'cognitive_state', None)
        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "请先配置模型。"}

        has_files = bool(self.context.metadata.get("uploaded_files"))
        file_hint = ""
        if has_files:
            files = self.context.metadata["uploaded_files"]
            names = [f.name for f in files]
            file_hint = "\n（用户上传了文件：{}）".format(", ".join(names))

        # 构建意图理解 prompt —— 给模型思考空间
        intent_system = (
            "你是任务理解专家。分析用户意图并决定处理方式。\n\n"
            "先思考：\n"
            "1. 用户真正想要什么？（深层需求，不只是字面意思）\n"
            "2. 期望的产出形态？（代码文件/文字分析/需要追问确认？操作记忆系统？）\n"
            "3. 如果有已有产物，是想改进还是在讨论别的？\n\n"
            "输出格式（严格）：\n"
            "ACTION: build | reply | clarify | memorize\n"
            "INTENT: 一句话描述用户真实意图\n"
            "- build: 需要产出可运行的文件（网页/工具/游戏/脚本/演示/可视化等）\n"
            "- reply: 纯文字对话（提问/分析/翻译/闲聊）\n"
            "- clarify: 意图模糊需要追问（如'继续优化'但不知道优化什么方向）\n"
            "- memorize: 操作记忆/知识系统（记住/查看/删除偏好、规则、记忆）\n"
        )

        # 构建用户消息——注入上下文让模型有足够信息判断
        has_prev_code = bool(self.context.artifacts.get("engineer_output"))
        user_msg = user_input + file_hint

        # 注入对话历史摘要（最近3轮）
        recent_turns = []
        for t in self.conversation.turns[-6:]:
            recent_turns.append("{}: {}".format(t.role, t.content[:100]))
        if recent_turns:
            user_msg += "\n\n[对话历史]\n" + "\n".join(recent_turns)

        # 注入当前产物状态
        if has_prev_code:
            code_files = self.context.artifacts.get("code_files", [])
            file_names = [f.split("/")[-1] for f in code_files[:3]]
            prev_request = ""
            for t in reversed(self.conversation.turns):
                if t.role == "user" and t.content != user_input:
                    prev_request = t.content
                    break
            # 提取产物结构摘要
            structure = self._get_artifact_structure()
            user_msg += "\n\n[当前产物] 文件: {} | 原始需求: {}\n结构: {}".format(
                ", ".join(file_names) if file_names else "无",
                prev_request[:80],
                structure[:200] if structure else "未知")

        try:
            log.info("_decide | user_input=%s", user_input[:80])
            log.debug("_decide | intent_system=%s", intent_system[:200])
            log.debug("_decide | user_msg=%s", user_msg[:300])
            result = await client.chat(
                messages=[
                    {"role": "system", "content": intent_system},
                    {"role": "user", "content": user_msg},
                ],
                model=self.config.default_model.model,
                max_tokens=200, temperature=0.0,
            )
            log.info("_decide | raw_response=%s", result[:200])
            decision = self._parse_intent(result)
        except Exception as e:
            log.error("_decide | exception: %s", str(e)[:100])
            decision = {"action": "reply", "intent": user_input, "form": ""}

        log.info("_decide | decision=%s", decision)
        self.context.metadata["_route_decision"] = decision
        self.context.metadata["_user_intent"] = decision.get("intent", user_input)
        _sid = self.context.metadata.get("session_id", "")
        log_activity(_sid, "decide",
                    action=decision.get("action", "?"),
                    intent=decision.get("intent", "")[:80])

        if decision["action"] == "reply":
            return await self._direct_reply(user_input, file_hint)
        if decision["action"] == "clarify":
            return {"action": "clarify", "question": await self._generate_clarify(user_input, decision)}
        if decision["action"] == "memorize":
            return await self._handle_memorize(user_input)
        return {"action": "code", "intent": decision.get("intent", user_input)}

    def _parse_intent(self, response: str) -> dict:
        """解析意图理解模型的结构化输出"""
        import re
        result = {"action": "reply", "intent": "", "form": "", "context": ""}

        action_m = re.search(r'ACTION:\s*(build|reply|clarify|memorize)', response, re.IGNORECASE)
        if action_m:
            result["action"] = action_m.group(1).lower()

        intent_m = re.search(r'INTENT:\s*(.+)', response)
        if intent_m:
            result["intent"] = intent_m.group(1).strip()

        form_m = re.search(r'FORM:\s*(.+)', response)
        if form_m:
            result["form"] = form_m.group(1).strip()

        context_m = re.search(r'CONTEXT:\s*(.+)', response)
        if context_m:
            result["context"] = context_m.group(1).strip()

        return result

    def _get_artifact_structure(self) -> str:
        """提取当前产物的结构摘要（不是全部代码）"""
        import re
        code_files = self.context.artifacts.get("code_files", [])
        if not code_files:
            return ""
        from pathlib import Path
        for fp in code_files[:1]:
            p = Path(fp)
            if p.exists():
                content = p.read_text(encoding="utf-8", errors="ignore")[:5000]
                # 提取关键结构
                titles = re.findall(r'<title>(.*?)</title>', content)
                buttons = re.findall(r'<button[^>]*>([^<]*)</button>', content)[:5]
                sections = re.findall(r'<(?:section|div)[^>]*(?:id|class)="([^"]*)"', content)[:8]
                funcs = re.findall(r'function\s+(\w+)', content)[:8]
                parts = []
                if titles:
                    parts.append("标题: " + titles[0])
                if buttons:
                    parts.append("按钮: " + ", ".join(buttons))
                if sections:
                    parts.append("模块: " + ", ".join(sections))
                if funcs:
                    parts.append("函数: " + ", ".join(funcs))
                return "; ".join(parts) if parts else "HTML文件 {}行".format(content.count("\n"))
        return ""

    async def _generate_clarify(self, user_input: str, decision: dict) -> str:
        """生成智能追问——基于当前产物结构，让模型自己决定问什么"""
        client = self._get_client()
        if not client:
            return "能具体说说你想怎么改进吗？"

        structure = self._get_artifact_structure()
        prompt = (
            "用户说：\"{}\"\n"
            "我理解的意图：{}\n"
            "当前产物结构：{}\n\n"
            "用户的指令不够明确，请生成一个简短的追问（2-3句话），"
            "帮助用户明确方向。要基于当前产物的具体内容给出具体的选项建议。"
            "直接输出追问文本，不要其他内容。"
        ).format(user_input, decision.get("intent", ""), structure or "无产物")

        try:
            clarify_text = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.default_model.model,
                max_tokens=200, temperature=0.3,
            )
            return clarify_text.strip()
        except Exception:
            return "能具体说说你想怎么改进吗？"

    def _build_confidence_context(self, user_input: str, cs) -> str:
        signals = []

        skill = self._match_skill(user_input)
        if skill:
            signals.append("技能库有匹配模板，此类任务有成功经验")

        if cs:
            if cs.task_success_rate >= 0.8:
                signals.append("该领域历史表现良好（{:.0f}%）".format(cs.task_success_rate * 100))
            elif cs.task_success_rate < 0.4 and cs.task_success_rate > 0:
                signals.append("该领域历史表现不佳")

            if cs.user_expertise == "advanced":
                signals.append("用户是有经验的用户，意图通常比较明确")

            if bool(self.context.artifacts.get("engineer_output")):
                signals.append("之前已生成过代码，用户可能在迭代改进")

        return "\n".join("- " + s for s in signals) if signals else ""

    # ═══════════════════════════════════════
    #  Agent执行器
    # ═══════════════════════════════════════

    async def _run_agent(self, agent_name: str, content: str, sender: str,
                         data: dict | None = None, timeout: int = 120) -> tuple[str, str]:
        agent = self.agents.get(agent_name)
        if not agent:
            return content, sender

        self.context.current_phase = agent_name
        self.observer.start_agent(agent_name)

        msg = Message(type=MessageType.TASK if sender != "user" else MessageType.USER_INPUT,
                      sender=sender, receiver=agent_name, content=content, data=data or {})
        self.context.add_message(msg)
        self.context.metadata["_notify_fn"] = self._notify
        self.context.metadata["_chunk_fn"] = self._notify_chunk

        output = content
        try:
            async def _execute():
                nonlocal output
                async for response in agent.handle(msg, self.context):
                    self.context.add_message(response)
                    self._notify(response)
                    self._display(response)
                    output = response.content

            await asyncio.wait_for(_execute(), timeout=timeout)
            self.observer.finish_agent(agent_name, success=True, summary=output[:80])
        except asyncio.TimeoutError:
            console.print(f"[yellow]⚠ [{agent_name}] 超时({timeout}s)[/yellow]")
            self.observer.finish_agent(agent_name, success=False, error=f"timeout({timeout}s)")
        except Exception as e:
            console.print(f"[red]⚠ [{agent_name}] 失败: {e}[/red]")
            self.observer.finish_agent(agent_name, success=False, error=str(e))

        return output, agent_name

    # ═══════════════════════════════════════
    #  工具
    # ═══════════════════════════════════════

    def _get_client(self):
        if not self.agents:
            return None
        return next(iter(self.agents.values())).model_client

    async def _handle_memorize(self, user_input: str):
        """用户要求记住/查看/删除知识——模型判断操作类型后执行"""
        client = self._get_client()
        if not client or not self.unified_store:
            return {"action": "reply", "content": "知识系统未初始化。"}

        try:
            result = await client.chat(
                messages=[
                    {"role": "system", "content": (
                        "用户在操作记忆系统。判断用户想做什么，输出JSON：\n"
                        "新增：{\"op\": \"add\", \"content\": \"知识内容\", "
                        "\"category\": \"preference|rule|pattern\", "
                        "\"domain\": \"tech|design|general\", "
                        "\"trigger\": \"应用场景\"}\n"
                        "查看：{\"op\": \"list\"}\n"
                        "删除：{\"op\": \"delete\", \"keyword\": \"要删除的知识关键词\"}\n"
                        "只输出JSON。"
                    )},
                    {"role": "user", "content": user_input},
                ],
                model=self.config.default_model.model,
                max_tokens=200, temperature=0.0,
            )
            import json as _json
            raw = result.strip().strip("```json").strip("```").strip()
            parsed = _json.loads(raw)
            op = parsed.get("op", "add")
            _sid = self.context.metadata.get("session_id", "")
            log_activity(_sid, "memorize_op", op=op, parsed=parsed)

            if op == "list":
                entries = self.unified_store._catalog
                if not entries:
                    reply = "当前没有已记录的知识。"
                else:
                    lines = [f"• {e['preview']}" for e in entries[:15]]
                    reply = f"已记录 {len(entries)} 条知识：\n" + "\n".join(lines)

            elif op == "delete":
                keyword = parsed.get("keyword", "")
                deleted = False
                for e in list(self.unified_store._catalog):
                    if keyword and keyword in e["preview"]:
                        path = self.unified_store.entries_dir / f"{e['id']}.json"
                        if path.exists():
                            path.unlink()
                        self.unified_store._catalog.remove(e)
                        deleted = True
                        break
                if deleted:
                    self.unified_store._save_catalog()
                    self.unified_store._invalidate_compiled()
                    reply = f"已删除包含「{keyword}」的知识。"
                else:
                    reply = f"未找到包含「{keyword}」的知识。"

            else:
                content = parsed.get("content", user_input)
                category = parsed.get("category", "insight")
                domain = parsed.get("domain", "general")
                trigger = parsed.get("trigger", "")
                conditions = []
                if trigger:
                    conditions.append({"type": "context", "value": trigger})
                self.unified_store.add(
                    content=content,
                    source="user",
                    maturity="pattern",
                    scope="project",
                    category=category,
                    domain=domain,
                    conditions=conditions,
                    session_id=self.context.metadata.get("session_id", ""),
                )
                reply = f"已记住：{content}"

            msg = Message(type=MessageType.RESULT, sender="assistant",
                         receiver="user", content=reply)
            self.context.add_message(msg)
            self.conversation.add_assistant(reply)
            if hasattr(self, 'state'):
                self.state.add_ai_reply(reply)
            return self.context
        except Exception as e:
            log.error("_handle_memorize | error: %s", str(e)[:100])
            # fallback：JSON解析失败时，直接把用户原话存为知识
            self.unified_store.add(
                content=user_input,
                source="user",
                maturity="observation",
                scope="project",
                session_id=self.context.metadata.get("session_id", ""),
            )
            reply = f"已记住（原文）：{user_input[:60]}"
            msg = Message(type=MessageType.RESULT, sender="assistant",
                         receiver="user", content=reply)
            self.context.add_message(msg)
            self.conversation.add_assistant(reply)
            if hasattr(self, 'state'):
                self.state.add_ai_reply(reply)
            return self.context

    async def _maybe_extract_knowledge(self, user_input: str, existing_ids: list[str]):
        """构建成功后，让模型判断是否有可复用的经验值得记录"""
        client = self._get_client()
        if not client or not self.unified_store:
            return
        try:
            transcript = self.context.metadata.get("_transcript")
            transcript_summary = ""
            if transcript:
                transcript_summary = "\n".join(
                    f"[{e.phase}] {e.content}" for e in transcript.entries[-8:])

            result = await client.chat(
                messages=[
                    {"role": "system", "content": (
                        "一次代码构建刚完成。判断这次构建过程中是否产生了可复用的经验。\n"
                        "可复用经验 = 下次遇到同类任务时能直接帮助的具体规则/模式/约束。\n"
                        "不是经验 = 只是正常完成了任务、没有特别的发现或教训。\n\n"
                        "如果有经验，输出JSON：{\"has_insight\": true, \"content\": \"一句话描述\", "
                        "\"category\": \"rule|pattern|pitfall\"}\n"
                        "如果没有，输出：{\"has_insight\": false}\n"
                        "只输出JSON。"
                    )},
                    {"role": "user", "content": (
                        f"用户需求：{user_input[:200]}\n"
                        f"构建过程：\n{transcript_summary[:500]}"
                    )},
                ],
                model=self.config.default_model.model,
                max_tokens=150, temperature=0.0,
            )
            import json as _json
            parsed = _json.loads(result.strip().strip("```json").strip("```"))
            if parsed.get("has_insight") and parsed.get("content"):
                self.unified_store.add(
                    content=parsed["content"],
                    source="auto",
                    maturity="observation",
                    scope="session",
                    category=parsed.get("category", "insight"),
                    domain="tech",
                    session_id=self.context.metadata.get("session_id", ""),
                )
                log_activity(self.context.metadata.get("session_id", ""),
                            "auto_extract", content=parsed["content"][:80])
                log.info("_maybe_extract_knowledge | extracted: %s", parsed["content"][:60])
        except Exception:
            pass

    def _match_skill(self, user_input: str) -> str | None:
        try:
            from deepforge.skills.builtin_skills import match_skill
            skill = match_skill(user_input)
            if skill and skill.get("prompt_template"):
                return skill["prompt_template"]
        except Exception:
            pass
        from deepforge.skills.registry import SkillRegistry
        try:
            sr = SkillRegistry(".deepforge/skills", ".deepforge/community_skills")
            results = sr.search(user_input)
            if results and results[0].prompt_template:
                return results[0].prompt_template
        except Exception:
            pass
        return None

    def _extract_and_store_knowledge(self, question: str, response: str, domain: str):
        """从高质量回答中提取知识点存入知识库——越用越强的核心"""
        import re
        if not self.knowledge or len(response) < 100:
            return

        # 提取回答中的关键句（含分析性表达的句子更有价值）
        sentences = re.split(r'[。\n]', response)
        valuable = []
        for s in sentences:
            s = s.strip()
            if len(s) < 15 or len(s) > 150:
                continue
            has_insight = bool(re.search(
                r'本质|核心|关键|原理|根本|因为|所以|这意味着|区别在于|值得注意',
                s
            ))
            if has_insight:
                valuable.append(s)

        # 取最有价值的前3句存入知识库
        for sent in valuable[:3]:
            triggers = self.knowledge._tokenize(question + " " + domain)
            self.knowledge.add(
                f"[{domain}] {sent}",
                triggers, "insight"
            )

    def _detect_domain(self, question: str, response: str) -> str:
        """从问题+回答综合判断领域——比单独分类问题更准"""
        import re
        combined = question + " " + response[:500]

        domain_signals = {
            "医学": r"症状|治疗|诊断|药物|发烧|疼痛|医院|病|就医|处方|剂量|手术",
            "法律": r"法律|合同|赔偿|维权|法院|诉讼|劳动法|违约|法条",
            "数学": r"证明|方程|概率|计算|公式|定理|求解|数学",
            "技术": r"代码|编程|算法|API|数据库|服务器|框架|Python|Java|bug|报错",
            "金融": r"投资|理财|基金|股票|贷款|利率|保险|收益|风险",
            "写作": r"写一篇|写一段|文案|文章|润色|演讲|致辞|开场白",
            "心理": r"焦虑|压力|情绪|迷茫|自卑|失眠|心理|抑郁|倦怠",
            "历史": r"朝代|历史|战争|皇帝|古代|王朝|革命|变法",
            "科学": r"物理|化学|生物|原子|量子|光速|DNA|基因|进化",
            "烹饪": r"做法|食材|火候|炒|煮|烤|蒸|菜|肉|汤|调料",
            "教育": r"学习|考试|备考|成绩|提分|方法|复习",
            "宠物": r"猫|狗|宠物|喂养|疫苗|绝育|呕吐|驱虫",
            "生活": r"装修|家电|清洗|维修|马桶|空调|洗衣机|甲醛",
            "健身": r"减肥|减脂|跑步|健身|蛋白粉|训练|增肌",
            "职场": r"简历|面试|跳槽|转行|加薪|晋升|职业",
        }

        best_domain = "通用"
        best_score = 0
        for domain, pattern in domain_signals.items():
            score = len(re.findall(pattern, combined, re.IGNORECASE))
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain if best_score >= 2 else "通用"

    async def _assess_complexity(self, user_input: str) -> str:
        client = self._get_client()
        if not client:
            return "simple"
        try:
            result = await client.chat(
                messages=[
                    {"role": "system", "content": (
                        "判断编程任务复杂度。\n"
                        "SIMPLE: 单文件能搞定，功能单一，<200行代码（如计算器、番茄钟、单位换算）\n"
                        "COMPLEX: 需要设计方案，多功能交互，>500行代码（如游戏、编辑器、管理系统、复杂应用）\n"
                        "只回复SIMPLE或COMPLEX")},
                    {"role": "user", "content": user_input},
                ],
                model=self.config.default_model.model,
                max_tokens=10,
                temperature=0.0,
            )
            return "complex" if "COMPLEX" in result else "simple"
        except Exception:
            return "simple"

    async def _generate_plans(self, user_input: str) -> list:
        client = self._get_client()
        if not client:
            return []
        try:
            result = await client.chat(
                messages=[
                    {"role": "system", "content": (
                        "为用户的编程需求生成2-3个实现方案。每个方案一行，格式：\n"
                        "方案N: [名称] | [一句话描述核心思路和功能] | 约XXX行\n"
                        "从简单到复杂排列。所有方案都必须在单个HTML文件内实现（内嵌CSS和JS）。\n"
                        "不要其他内容。")},
                    {"role": "user", "content": user_input},
                ],
                model=self.config.default_model.model,
                max_tokens=300,
                temperature=0.3,
            )
            plans = []
            for line in result.strip().split("\n"):
                line = line.strip()
                if not line or "方案" not in line:
                    continue
                parts = line.split("|")
                if len(parts) >= 2:
                    title = parts[0].split(":", 1)[-1].strip() if ":" in parts[0] else parts[0].strip()
                    desc = parts[1].strip()
                    est = parts[2].strip() if len(parts) > 2 else ""
                    plans.append({"id": len(plans) + 1, "title": title, "desc": desc, "est": est})
            return plans[:3]
        except Exception:
            return []

    async def run_with_plan(self, user_input: str, plan: dict, user_note: str = "") -> "WorkContext":
        plan_desc = "{}：{}".format(plan.get("title", ""), plan.get("desc", ""))
        if user_note:
            plan_desc += "\n用户补充：{}".format(user_note)
        build_input = "{}（方案：{}）".format(user_input, plan_desc)
        self.context.metadata["_plan_confirmed"] = True
        self.context.artifacts.pop("code_files", None)
        self.context.artifacts.pop("engineer_output", None)
        self.context.user_request = build_input

        # Update transcript with plan selection
        transcript = self.context.metadata.get("_transcript")
        if transcript:
            transcript.add("plan", "user", "选择了: {}".format(plan.get("title", "")))
            transcript.plan_summary = plan_desc[:100]
            transcript.current_phase = "build"

        return await self._run_build(build_input)

    async def _evolve_one_step(self, current_question: str):
        """懒评估——每5次交互评估1个问题，用pairwise比较（1次LLM调用）"""
        if not self.self_evolver or not self.self_evolver.evolving:
            return
        try:
            client = self._get_client()
            if not client:
                return
            from deepforge.core.activation_engine import ACTIVATION_PROMPT

            q = current_question
            model = self.config.default_model.model
            max_tokens = self.config.default_model.max_tokens
            sys_cur = ACTIVATION_PROMPT.format(activation_seed=self.self_evolver.current_best, extra_context="")
            sys_cand = ACTIVATION_PROMPT.format(activation_seed=self.self_evolver._candidate, extra_context="")

            resp_cur = await asyncio.wait_for(client.chat(
                messages=[{"role": "system", "content": sys_cur},
                          {"role": "user", "content": q}],
                model=model, max_tokens=max_tokens), timeout=30)
            resp_cand = await asyncio.wait_for(client.chat(
                messages=[{"role": "system", "content": sys_cand},
                          {"role": "user", "content": q}],
                model=model, max_tokens=max_tokens), timeout=30)

            judge_result = await asyncio.wait_for(client.chat(
                messages=[
                    {"role": "system", "content": "比较两个回答，哪个对用户更有帮助？只回复A或B。"},
                    {"role": "user", "content": "问题：{}\n\n回答A：{}\n\n回答B：{}".format(
                        q, resp_cur[:300], resp_cand[:300])},
                ],
                model=model, max_tokens=5, temperature=0.0), timeout=15)

            choice = "A" if "A" in judge_result.strip()[:3] else "B"
            import random
            if random.random() > 0.5:
                winner = "current" if choice == "A" else "candidate"
            else:
                winner = "candidate" if choice == "A" else "current"

            self.self_evolver._ab_results.append({
                "question": q[:50], "winner": winner,
            })
            console.print("[dim]  self-evolver: eval {}/{} -> {}[/dim]".format(
                len(self.self_evolver._ab_results), 10, winner))
        except Exception as e:
            console.print("[dim]  self-evolver step error: {}[/dim]".format(str(e)[:60]))

    async def _run_self_evolution(self):
        """后台完整进化循环：生成候选→回放历史问题→judge比较→finalize"""
        if not self.self_evolver:
            return
        try:
            await self.self_evolver.generate_candidate()
            if not self.self_evolver.evolving:
                return

            client = self._get_client()
            if not client:
                return

            from deepforge.core.activation_engine import ACTIVATION_PROMPT
            from deepforge.core.checklist_judge import evaluate

            questions = self._get_recent_questions(n=10)
            if len(questions) < 5:
                questions = [
                    "什么是人工智能", "TCP三次握手的过程",
                    "红烧肉怎么做", "光速为什么不能被超越",
                    "工作三年感觉迷茫怎么办",
                ]

            current_seed = self.self_evolver.current_best
            candidate_seed = self.self_evolver._candidate
            model = self.config.default_model.model
            max_tokens = self.config.default_model.max_tokens

            sys_current = ACTIVATION_PROMPT.format(activation_seed=current_seed, extra_context="")
            sys_candidate = ACTIVATION_PROMPT.format(activation_seed=candidate_seed, extra_context="")

            for q in questions:
                try:
                    resp_cur = await asyncio.wait_for(client.chat(
                        messages=[{"role": "system", "content": sys_current},
                                  {"role": "user", "content": q}],
                        model=model, max_tokens=max_tokens), timeout=30)
                    resp_cand = await asyncio.wait_for(client.chat(
                        messages=[{"role": "system", "content": sys_candidate},
                                  {"role": "user", "content": q}],
                        model=model, max_tokens=max_tokens), timeout=30)

                    eval_cur = await asyncio.wait_for(
                        evaluate(client, model, q, resp_cur), timeout=30)
                    eval_cand = await asyncio.wait_for(
                        evaluate(client, model, q, resp_cand), timeout=30)

                    winner = "candidate" if eval_cand.coverage > eval_cur.coverage else "current" if eval_cur.coverage > eval_cand.coverage else "tie"
                    self.self_evolver._ab_results.append({
                        "question": q[:50],
                        "current_score": eval_cur.coverage,
                        "candidate_score": eval_cand.coverage,
                        "winner": winner,
                    })
                    console.print("[dim]  self-evolver: evaluated '{}' -> {}[/dim]".format(q[:20], winner))
                except Exception as e:
                    console.print("[dim]  self-evolver eval error: {}[/dim]".format(str(e)[:60]))

            if self.self_evolver.ab_complete():
                result = self.self_evolver.finalize()
                if result.get("result") == "evolved" and self.activation_engine:
                    self.activation_engine._current_seed = self.self_evolver.current_best
                console.print("[dim]  self-evolver: cycle complete - {}[/dim]".format(
                    result.get("result", "?")))
        except Exception as e:
            console.print("[red]  self-evolver error: {}[/red]".format(str(e)[:100]))

    def _get_recent_questions(self, n: int = 10) -> list:
        questions = []
        for turn in reversed(self.conversation.turns):
            if turn.role == "user" and len(turn.content) > 5:
                questions.append(turn.content)
                if len(questions) >= n:
                    break
        return questions

    async def _evolve_from_result(self):
        """后台静默进化——用户无感知"""
        try:
            from deepforge.core.evolution import evolve_from_output
            engineer_output = self.context.artifacts.get("engineer_output", "")
            user_request = self.context.user_request
            if engineer_output:
                evolve_from_output(engineer_output, user_request, self.knowledge)
        except Exception:
            pass

    def _feedback_success(self):
        """有质量门控的反馈——只对非负向信号的回答标记成功"""
        if not self.knowledge:
            return

        signal = self.context.metadata.get("_last_user_signal", "unknown")
        if signal in ("error", "unsatisfied"):
            return

        recalled_ids = getattr(self.knowledge, '_last_recalled_ids', [])
        for eid in recalled_ids:
            self.knowledge.record_success(eid)
            if eid in self.knowledge._entries:
                self.knowledge._entries[eid].usage_count += 1
        if recalled_ids:
            self.knowledge._compile_l1()

        if self.knowledge.stats()["total"] > 500:
            self.knowledge.prune(max_entries=400)

    async def _audit(self, question: str, response: str) -> str:
        """反幻觉审计——标注不可靠内容"""
        try:
            from deepforge.core.hallucination_guard import audit_response
            client = self._get_client()
            if not client:
                return response
            return await audit_response(
                question, response, client,
                model=self.config.default_model.model,
                max_tokens=self.config.default_model.max_tokens,
                mode=self.config.hallucination_guard.mode,
            )
        except Exception:
            return response

    def _is_text_task(self, user_input: str) -> bool:
        """只有明确要做工具/网页/游戏才走code，其他全部走text"""
        import re
        code_patterns = [
            r"做一个|创建一个|生成一个|开发一个|搭建一个",
            r"做个|写个|弄个|搞个",
            r"网页|网站|工具|游戏|扩展|脚本|程序|应用|APP|app",
            r"可视化|图表|看板|仪表盘|dashboard",
        ]
        code_score = sum(1 for p in code_patterns if re.search(p, user_input))
        return code_score == 0

    async def _direct_reply(self, user_input: str, file_hint: str = "") -> dict:
        """用激发引擎构建prompt——带对话历史和上下文信号"""
        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "请先配置模型。"}

        # 延迟初始化SelfEvolver（需要client可用）
        if not self.self_evolver and client:
            try:
                from deepforge.core.self_evolver import SelfEvolver
                from deepforge.core.activation_engine import DEFAULT_ACTIVATION_SEED
                self.self_evolver = SelfEvolver(
                    client, self.config.default_model.model, DEFAULT_ACTIVATION_SEED)
            except Exception:
                pass

        file_context = self.context.metadata.get("uploaded_files_text", "")

        domain_context = self.context.metadata.get("domain_knowledge", "")
        l1 = []
        if self.unified_store:
            l1 = self.unified_store.get_l1_compiled()
        elif self.knowledge:
            l1 = self.knowledge.get_l1_compiled()

        recalled = []
        if self.distiller:
            detected_domain = self._detect_domain(user_input, "")
            recalled = self.distiller.recall_for_domain(user_input, detected_domain, max_results=3)
        elif self.knowledge:
            recalled = self.knowledge.recall(user_input, max_results=5)

        all_knowledge = []
        for k in recalled:
            if k in all_knowledge:
                continue
            if not k.startswith("["):
                continue
            if k.startswith("[成功]") or k.startswith("[seed") or k.startswith("[失败]"):
                continue
            all_knowledge.append(k[:120])
        all_knowledge = all_knowledge[:3]

        # 上下文信号注入
        ctx_hint = ""
        ctx_signals = self.context.metadata.get("_context_signals")
        if ctx_signals and self.context_analyzer:
            ctx_hint = self.context_analyzer.build_context_hint(ctx_signals)

        # 用户画像注入
        profile_hint = ""
        session_id = self.context.metadata.get("session_id", "")
        if self.profile_manager and session_id:
            profile = self.profile_manager.get_or_create(session_id)
            profile_hint = profile.get_activation_hint()

        if self.activation_engine:
            cs = getattr(self, 'cognitive_state', None)
            if cs and cs.best_seed:
                self.activation_engine._current_seed = cs.best_seed
            system = self.activation_engine.build_activation_prompt(
                user_input=user_input,
                domain_context=domain_context + ctx_hint + profile_hint,
                l1_compiled=all_knowledge[:8] if all_knowledge else None,
            )
        else:
            system = "你是一位专业的AI助手，请准确回答用户的问题。"

        history = self.conversation.get_history_for_llm()
        # 截断过长的assistant回复（代码输出等），保留最近对话
        cleaned = []
        for h in history:
            content = h.get("content", "")
            if len(content) > 1500:
                cleaned.append({"role": h["role"], "content": content[:300] + "\n...(内容过长已截断)"})
            else:
                cleaned.append(h)
        history = cleaned[-6:]
        user_content = user_input + ("\n{}".format(file_hint) if file_hint else "") + ("\n{}".format(file_context) if file_context else "")

        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})

        try:
            # Streaming输出——用户实时看到回答生成
            raw = ""
            try:
                async for chunk in client.chat_stream(
                    messages=messages,
                    model=self.config.default_model.model,
                    max_tokens=self.config.default_model.max_tokens,
                ):
                    raw += chunk
                    self._notify_chunk("assistant", chunk)
            except Exception:
                if not raw:
                    raw = await client.chat(
                        messages=messages,
                        model=self.config.default_model.model,
                        max_tokens=self.config.default_model.max_tokens,
                    )

            # ResponseValidator：通用语义验证
            from deepforge.core.response_validator import should_validate, validate_response, build_retry_prompt
            if should_validate(user_input, raw, self.conversation.turns):
                vr = await validate_response(
                    client, self.config.default_model.model,
                    user_input, raw)
                self.context.metadata["_validation_result"] = vr
                if not vr["relevant"]:
                    retry_prompt = build_retry_prompt(
                        user_input, vr, self.conversation.turns)
                    messages[-1] = {"role": "user", "content": retry_prompt}
                    raw = await client.chat(
                        messages=messages,
                        model=self.config.default_model.model,
                        max_tokens=self.config.default_model.max_tokens,
                    )
                    console.print("[dim]  validator: off-topic detected, regenerated[/dim]")

            domain_tag = ""
            if self.activation_engine:
                activated = self.activation_engine.parse_activated_response(raw)

                # 领域识别：从回答+问题综合判断
                domain_tag = activated.domain or ""
                if not domain_tag or domain_tag == "通用":
                    domain_tag = self._detect_domain(user_input, raw)

                self.context.metadata["expert_name"] = domain_tag
                self.context.metadata["activation_confidence"] = activated.overall_confidence
                console.print("[dim]  {} | {}: {}[/dim]".format(
                    domain_tag, "confidence", activated.overall_confidence))

                # 精准知识蒸馏（替代Phase 0被禁用的旧策略）
                user_signal = self.context.metadata.get("_last_user_signal", "neutral")
                if self.distiller and raw and len(raw) > 100:
                    distilled = self.distiller.distill(user_input, raw, domain_tag, user_signal)
                    if distilled:
                        console.print("[dim]  distilled {} facts[/dim]".format(len(distilled)))

                signal_weight = self.context.metadata.get("_last_signal_weight", 0.0)
                vr = self.context.metadata.get("_validation_result", {})
                relevance = 1.0 if vr.get("relevant", True) else 0.3
                self.quality_tracker.record(
                    question=user_input, domain=domain_tag,
                    seed=self.activation_engine._current_seed[:60],
                    response=raw, user_signal=user_signal,
                    signal_weight=signal_weight,
                    model=self.config.default_model.model,
                    relevance=relevance,
                )

                # 异步checklist评估（不阻塞响应）
                async def _bg_judge():
                    try:
                        from deepforge.core.checklist_judge import evaluate
                        result = await evaluate(client, self.config.default_model.model, user_input, raw)
                        self.context.metadata["_judge_score"] = result.to_dict()
                    except Exception:
                        pass
                asyncio.create_task(_bg_judge())

                # 每20次回答触发一次evolver演化
                if hasattr(self.activation_engine, '_evolver') and self.activation_engine._evolver:
                    self.activation_engine._use_count += 1
                    if self.activation_engine._use_count % 20 == 0:
                        try:
                            result = self.activation_engine._evolver.analyze_and_evolve()
                            if result.get("status") == "evolved":
                                console.print("[dim]Evolution gen {} - {} domains optimized[/dim]".format(
                                    result["generation"], result["domains_optimized"]))
                        except Exception:
                            pass

                # (SelfEvolver已移至run()入口统一处理)
            else:
                self.context.metadata["expert_name"] = "DeepForge"

            self.context.artifacts["last_text_domain"] = domain_tag
            self.conversation.add_assistant(raw, domain=domain_tag)
            if hasattr(self, 'state'):
                self.state.add_ai_reply(raw)

            # 四信号融合可信度评估
            if self.credibility:
                cred = self.credibility.assess(
                    user_input, raw, domain_tag,
                    user_signal=self.context.metadata.get("_last_user_signal", "neutral"))
                self.context.metadata["credibility"] = cred
                self.context.metadata["activation_confidence"] = cred["level"]

            # 记录到用户画像
            if self.profile_manager and session_id:
                profile = self.profile_manager.get_or_create(session_id)
                profile.record_turn(user_input, domain_tag, is_code=False,
                                   signal=self.context.metadata.get("_last_user_signal", "neutral"))

            return {"action": "reply", "content": raw}
        except Exception as e:
            return {"action": "reply", "content": f"出错了: {e}"}
