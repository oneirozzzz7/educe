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

log = logging.getLogger("educe.orchestrator")

from educe.core.activity_log import log_activity
from educe.core.logging import SessionLogger, get_logger as get_session_logger

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from educe.core.agent import BaseAgent
from educe.core.config import EduceConfig
from educe.core.message import Message, MessageType, WorkContext
from educe.core.observer import Observer
from educe.core.task_store import TaskStore
from educe.core.event_bus import EventBus
from educe.core.knowledge import LayeredCache
from educe.core.action_executors import ActionExecutorMixin
from educe.core.build_mixin import BuildMixin
from educe.core.decision_mixin import DecisionMixin
from educe.core.evolution_mixin import EvolutionMixin

console = Console()


class Orchestrator(ActionExecutorMixin, BuildMixin, DecisionMixin, EvolutionMixin):
    def __init__(self, config: EduceConfig, max_iterations: int = 3):
        self.config = config
        self.agents: dict[str, BaseAgent] = {}
        self.context = WorkContext()
        self.max_iterations = max_iterations
        self.observer = Observer()
        self.task_store = TaskStore()
        self.bus = EventBus()
        self.knowledge = LayeredCache()
        self.session_logger: SessionLogger | None = None
        self._module_health: dict[str, str] = {}

        from educe.core.unified_store import UnifiedKnowledgeStore
        self.unified_store = self._try_init("unified_store",
            lambda: UnifiedKnowledgeStore(Path(".educe/unified")))

        from educe.core.session_store import SessionStore
        self.session_store = SessionStore()

        from educe.core.conversation import ConversationManager
        self.conversation = ConversationManager(knowledge=self.knowledge)

        from educe.core.quality_tracker import QualityTracker
        self.quality_tracker = QualityTracker()

        from educe.core.domain_engine import DomainEngine
        self.domain_engine = self._try_init("domain_engine",
            lambda: DomainEngine(knowledge=self.knowledge))

        from educe.core.activation_engine import ActivationEngine
        self.activation_engine = self._try_init("activation_engine",
            lambda: ActivationEngine(knowledge=self.knowledge, domain_engine=self.domain_engine))

        from educe.core.context_analyzer import ContextAnalyzer
        self.context_analyzer = self._try_init("context_analyzer",
            lambda: ContextAnalyzer())

        from educe.core.knowledge_distiller import KnowledgeDistiller
        self.distiller = self._try_init("distiller",
            lambda: KnowledgeDistiller(self.knowledge))

        from educe.core.user_profile import UserProfileManager
        self.profile_manager = self._try_init("profile_manager",
            lambda: UserProfileManager())

        from educe.core.credibility_engine import CredibilityEngine
        self.credibility = self._try_init("credibility",
            lambda: CredibilityEngine(knowledge=self.knowledge, quality_tracker=self.quality_tracker))

        self.self_evolver = None

        from educe.core.decision_ledger import DecisionLedger
        self.decision_ledger = DecisionLedger(Path(".educe/logs/decisions"))

        from educe.core.environment_observer import EnvironmentObserver
        self.env_observer = EnvironmentObserver()

        from educe.core.effect_stream import EffectStream
        self.effects = EffectStream()

        from educe.core.streaming_registry import StreamingRegistry
        self.streaming_registry = StreamingRegistry()

        self.verbosity_organ = None
        self.organ_registry = None
        self._init_organs()

        self._on_message: list[Callable] = []
        self._on_chunk: list[Callable] = []

        disabled_count = sum(1 for v in self._module_health.values() if v.startswith("disabled"))
        if disabled_count > 0:
            log.warning("orchestrator init: %d module(s) disabled — %s",
                        disabled_count,
                        ", ".join(k for k, v in self._module_health.items() if v.startswith("disabled")))

    def _try_init(self, name: str, factory: Callable) -> object | None:
        try:
            result = factory()
            self._module_health[name] = "ok"
            return result
        except Exception as e:
            log.warning("module disabled: %s — %s: %s", name, type(e).__name__, e)
            self._module_health[name] = f"disabled: {type(e).__name__}: {e}"
            return None

    def _init_organs(self) -> None:
        try:
            from educe.core.organ_verbosity import VerbosityOrgan
            from educe.core.organ_codelang import CodeLangOrgan
            from educe.core.organ_registry import OrganRegistry
            self.verbosity_organ = VerbosityOrgan(bus=self._get_evolution_bus())
            self.organ_registry = OrganRegistry()
            self.organ_registry.register(self.verbosity_organ)
            self.organ_registry.register(CodeLangOrgan())
            self._module_health["organs"] = "ok"
        except Exception as e:
            log.warning("module disabled: organs — %s: %s", type(e).__name__, e)
            self._module_health["organs"] = f"disabled: {type(e).__name__}: {e}"

    # ═══════════════════════════════════════
    #  记忆自动写入基础设施
    # ═══════════════════════════════════════

    _AUTO_MEMORY_SESSION_LIMIT = 5
    _AUTO_MEMORY_TOTAL_CAP = 100

    def _auto_write_memory(self, mem_type: str, content: str, *,
                           scope: str = "", tags: list | None = None,
                           detail_key: str = "") -> bool:
        """统一入口：自动写入记忆（带去重、限速、冲突检测、透明日志）。

        Returns True if written, False if skipped (dedup/rate-limit/conflict).
        """
        from educe.core.project_memory import ProjectMemoryStore, MemoryEntry
        import time as _time_mem
        import hashlib

        count = self.context.metadata.get("_auto_memory_count", 0)
        if count >= self._AUTO_MEMORY_SESSION_LIMIT:
            log.debug("auto_memory rate-limited (session cap %d)", self._AUTO_MEMORY_SESSION_LIMIT)
            return False

        try:
            store = ProjectMemoryStore()
        except Exception as e:
            log.debug("auto_memory store unavailable: %s", e)
            return False

        key = detail_key or content[:40].lower().strip()
        for existing in store.get_all():
            if existing.type == mem_type and key in (existing.tags or []):
                existing.confidence = min(1.0, existing.confidence + 0.05)
                existing.provenance.setdefault("confirmed", []).append(
                    _time_mem.strftime("%Y-%m-%d"))
                store._save()
                log.info("auto_memory reinforced: [%s] %s (+0.05)", mem_type, key[:40])
                return False

        if len(store.get_all()) >= self._AUTO_MEMORY_TOTAL_CAP:
            expired = [e for e in store.get_all() if e.confidence < 0.35]
            if expired:
                for e in expired[:5]:
                    store.remove(e.id)
                log.info("auto_memory evicted %d low-confidence entries", min(5, len(expired)))

        mem_id = hashlib.md5(f"{mem_type}:{key}".encode()).hexdigest()[:12]
        entry = MemoryEntry(
            id=mem_id,
            type=mem_type,
            content=content,
            confidence=0.5 if mem_type != "scar" else 0.4,
            scope=scope,
            tags=(tags or []) + [key],
            provenance={"born": _time_mem.strftime("%Y-%m-%d %H:%M"), "confirmed": [], "challenged": []},
            verified_at=_time_mem.time(),
        )

        # 冲突检测：同类型+同范围+标签交集但内容不同 → 标记双方为 disputed
        conflicts = store.find_conflicts(entry)
        if conflicts:
            conflict_ids = [c.id for c in conflicts]
            store.add(entry)
            store.mark_disputed([entry.id] + conflict_ids)
            self.context.metadata["_auto_memory_count"] = count + 1
            log.warning("auto_memory CONFLICT: new [%s] '%s' vs %d existing entries",
                        mem_type, content[:40], len(conflicts))
            self._slog("memory", "conflict_detected",
                       summary=f"[{mem_type}] {content[:40]} conflicts with {len(conflicts)} entries",
                       data={"new_id": mem_id, "conflict_ids": conflict_ids,
                             "new_content": content, "existing": [c.content for c in conflicts]})
            # 推送冲突事件到前端
            import json as _json_conflict
            self._emit_tool_event({
                "type": "memory_conflict",
                "new_entry": {"id": mem_id, "type": mem_type, "content": content},
                "conflicts": [{"id": c.id, "type": c.type, "content": c.content,
                               "born": c.provenance.get("born", "")} for c in conflicts],
            })
            return True

        store.add(entry)
        self.context.metadata["_auto_memory_count"] = count + 1
        log.info("auto_memory written: [%s] %s (confidence=%.2f)", mem_type, content[:60], entry.confidence)
        self._slog("memory", "auto_write",
                   summary=f"[{mem_type}] {content[:60]}",
                   data={"type": mem_type, "content": content, "key": key})
        return True

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

    def _emit_tool_event(self, event: dict) -> None:
        """推送 tool_start/tool_chunk/tool_end 到前端（顶层 WS 消息类型）"""
        import json as _json_te
        msg = Message(
            type=MessageType.SYSTEM, sender="system", receiver="user",
            content="__TOOL_EVENT__" + _json_te.dumps(event, ensure_ascii=False))
        self._notify(msg)

    def _slog(self, type: str, name: str, **kwargs) -> None:
        """Structured log + EvolutionEvent 总线投影。

        无条件先写日志（零丢失），然后查注册表决定是否进总线。
        """
        # 1. 日志无条件先写（向后兼容）
        sl = self.session_logger or get_session_logger()
        if sl:
            sl.event(type=type, name=name, **kwargs)

        # 2. 查注册表，命中才进总线
        from educe.core.evolution_bus import EVOLUTION_BUILDERS
        builder = EVOLUTION_BUILDERS.get((type, name))
        if builder:
            event = builder.build(kwargs)
            if event and event.passes_three_gates():
                bus = self._get_evolution_bus()
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(bus.emit(event))
                    else:
                        loop.run_until_complete(bus.emit(event))
                except RuntimeError:
                    pass

    def _display(self, msg: Message) -> None:
        icon = {"builder": "💻", "tester": "🧪", "planner": "📋", "assistant": "💬"}.get(msg.sender, "🤖")
        console.print(Panel(Markdown(msg.content[:500]), title=f"{icon} {msg.sender}", border_style="cyan", padding=(0, 1)))

    # ═══════════════════════════════════════
    #  唯一入口
    # ═══════════════════════════════════════

    async def run(self, user_input: str, file_content: str | None = None) -> WorkContext:
        self.context.user_request = user_input
        _sid = self.context.metadata.get("session_id", "")

        # 确保 shell 执行的 cwd 默认为项目根（启动时的工作目录）
        if not self.context.metadata.get("_project_context_path"):
            import os
            self.context.metadata["_project_context_path"] = os.getcwd()

        log_activity(_sid, "user_input", input=user_input[:200],
                     has_file=bool(file_content))

        sl = self.session_logger or get_session_logger()
        if sl:
            sl.set_task(user_input)
            self._slog("framework", "session_start",
                       summary=f"user: {user_input[:80]}",
                       data={"has_file": bool(file_content)})

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

            # 记忆自动写入：用户纠正 → buffer for convention
            if signal == "error":
                self.context.metadata["_correction_pending"] = user_input
            elif signal in ("grateful", "engaged", "neutral") and self.context.metadata.get("_correction_pending"):
                pending = self.context.metadata.pop("_correction_pending")
                self._auto_write_memory(
                    "convention",
                    f"User correction: {pending[:120]}",
                    detail_key=pending[:40].lower().strip(),
                )
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

            # ═══ BehaviorLearner: 从纠正中学习 ═══
            if signal in ("error", "unsatisfied") and prev_assistant:
                asyncio.create_task(self._learn_from_correction(prev_assistant, user_input))
            # ═══ BehaviorLearner: match成功后强化/惩罚（信用分配：只作用最相关的1条）═══
            matched_unit_ids = self.context.metadata.get("_matched_behavior_units", [])
            if matched_unit_ids:
                learner = self._get_behavior_learner()
                is_positive = signal in ("grateful", "engaged")
                is_negative = signal in ("error", "unsatisfied")
                if is_positive:
                    # 只强化排名第一的 unit（effective_weight 最高 = 最可能贡献的）
                    learner.reinforce(matched_unit_ids[0])
                elif is_negative:
                    # 惩罚也只作用最相关的那条，避免误伤
                    learner.penalize(matched_unit_ids[0])
                learner.lifecycle_check()

            # ═══ BehaviorLearner: 静默对照记录（withheld units 的 baseline）═══
            withheld_ids = self.context.metadata.get("_withheld_behavior_units", [])
            if withheld_ids:
                learner = self._get_behavior_learner()
                is_positive = signal in ("grateful", "engaged", "neutral")
                for uid in withheld_ids:
                    learner.record_baseline(uid, compliant=is_positive)

        # ═══ 清除上一轮状态 ═══
        self.context.metadata.pop("_recalled_knowledge_ids", None)
        self.context.metadata.pop("_matched_behavior_units", None)
        self.context.metadata.pop("_withheld_behavior_units", None)
        self.context.metadata.pop("_failed_actions", None)
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

        # ═══ 如果模型在等用户回答澄清问题 → 把回答合并到原始请求继续执行 ═══
        if self.context.metadata.get("_clarify_pending"):
            original = self.context.metadata.pop("_pending_user_input", "")
            self.context.metadata.pop("_clarify_pending", None)
            self._slog("user", "clarify_resume",
                       summary=f"answer: {user_input[:80]}",
                       data={"answer": user_input[:200]})
            combined = f"{original}\n\n用户补充：{user_input}"
            self.conversation.add_user(user_input)
            if hasattr(self, 'state'):
                self.state.add_user_input(user_input)
            return await self._action_loop(combined, self.context.metadata.get("_transcript"))

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
        from educe.core.transcript import TaskTranscript
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
        from educe.core.action_executor import parse_actions
        from educe.core.context_manager import build_context, SessionMemory

        client = self._get_client()
        if not client:
            msg = Message(type=MessageType.RESULT, sender="assistant",
                         receiver="user", content="请先配置模型。")
            self.context.add_message(msg)
            self._notify(msg)
            return self.context

        _sid = self.context.metadata.get("session_id", "")

        # L1 澄清：高危不可逆操作确认（L0公理级安全规则）
        clarification = self._l1_clarification_check(user_input)
        if clarification:
            msg = Message(type=MessageType.RESULT, sender="assistant",
                         receiver="user", content=clarification)
            self.context.add_message(msg)
            self._notify(msg)
            self.conversation.add_assistant(clarification)
            return self.context

        # 阶段3: ReflexRouter — LLM 入口前分诊（L3+ skill 直接执行）
        import os as _os_flag
        _bare_mode = _os_flag.environ.get("EDUCE_BARE_MODE", "0") == "1"

        reflex_hint = ""
        if not _bare_mode:
            reflex_hint = await self._try_reflex(user_input)
            if reflex_hint is None:
                return self.context  # 反射完成，跳过 LLM

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

        # 获取 connector Level 1 描述（预加载 MCP capabilities）
        cr = self._get_connector_registry()
        if not hasattr(self, '_connectors_preloaded'):
            try:
                await cr.preload_capabilities()
                self._connectors_preloaded = True
            except Exception as e:
                log.warning("connector preload failed: %s", e)
                self._connectors_preloaded = False
        connector_summary = cr.get_level1_descriptions()

        system = build_context(
            session_memory=session_memory,
            catalog=catalog,
            tools=[{"name": t.name, "description": t.description} for t in self._get_tool_registry().list_all()],
            seed=seed,
            connectors_summary=connector_summary,
        )

        # BehaviorManifest 注入：active + staged 全量注入（模型自己做 NLI）
        # staged 需要试用机会才能积累数据晋升
        manifest = self._get_behavior_manifest()
        if manifest:
            learner = self._get_behavior_learner()
            candidates = manifest.active_units() + manifest.staged_units()

            # 静默对照：部分 unit 不注入，用于积累 marginal_value 数据
            injected_ids = []
            withheld_ids = []
            for u in candidates:
                if learner.should_withhold(u.id):
                    withheld_ids.append(u.id)
                else:
                    injected_ids.append(u.id)

            # Phase 0 埋点：行为规则注入/抑制决策
            if withheld_ids:
                self.decision_ledger.record(
                    "behavior_withhold", "framework",
                    f"withhold {len(withheld_ids)} behavior units for A/B",
                    context={"withheld": withheld_ids, "injected": injected_ids})

            # 渲染注入（排除 withheld 的）
            if injected_ids:
                behavior_rules = manifest.render_for_prompt("")  # 不传 context，全量注入
                if behavior_rules and behavior_rules != manifest.base_seed:
                    system += f"\n{behavior_rules}"

            # 记录本轮状态
            if injected_ids:
                self.context.metadata["_matched_behavior_units"] = injected_ids
            else:
                self.context.metadata.pop("_matched_behavior_units", None)
            if withheld_ids:
                self.context.metadata["_withheld_behavior_units"] = withheld_ids

        # 阶段1: 决策前因果检索 — 从账本中提取相关经验注入 prompt
        if not _bare_mode:
            causal_experience = await self._get_causal_retriever().retrieve_experience(user_input)
            if causal_experience:
                system += causal_experience

        # 阶段2: CompositeSkill 注入 — 匹配已编译技能，引导一口气执行
        if not _bare_mode:
            skill_prompt = self._match_composite_skills(user_input, round_idx=0)
            if skill_prompt:
                self.decision_ledger.record(
                    "skill_inject", "framework",
                    f"inject composite skill into prompt",
                    context={"input": user_input[:200], "skill_prompt_len": len(skill_prompt)})
                system += skill_prompt

        # 阶段3: ReflexRouter 降级提示（守卫失败或准反射时附加）
        if not _bare_mode and reflex_hint:
            system += reflex_hint

        # 器官注入：所有器官的 system prompt 注入
        if not _bare_mode and self.organ_registry:
            _organ_hints = self.organ_registry.collect_injections()
            if _organ_hints:
                system += f"\n\n## 用户偏好\n{_organ_hints}"

        # 复利记忆：项目知识/教训/约定注入
        if not _bare_mode:
            try:
                from educe.core.project_memory import ProjectMemoryStore
                _mem_store = ProjectMemoryStore()
                _mem_injection = _mem_store.build_prompt_injection()
                if _mem_injection:
                    system += f"\n\n{_mem_injection}"
            except Exception as e:
                log.warning("project memory injection skipped: %s", e)

        # Prober: 注入 OPEN claims 让模型感知未验证知识
        if _sid:
            try:
                state, log_obj = self._get_iteration_state(_sid)
                open_claims = state.open_hyp()
                if open_claims:
                    claims_text = "\n".join(f"- {c.text}" for c in open_claims[:5])

                    # 诚实退出检测：收敛曲线是否停滞
                    curve = log_obj.convergence_curve()
                    stall_threshold = 5
                    is_stalled = False
                    if len(curve) >= stall_threshold and curve[-1] < 1.0:
                        recent = curve[-stall_threshold:]
                        variation = max(recent) - min(recent)
                        is_stalled = variation < 0.02

                    if is_stalled:
                        system += (
                            f"\n\n## ⚠️ 收敛停滞\n"
                            f"以下问题已经连续 {stall_threshold} 轮没有进展，当前模型可能无法解决：\n"
                            f"{claims_text}\n"
                            f"请诚实告知用户：这个问题你可能需要换个思路、拆分任务、或人工介入。"
                            f"不要继续重复相同的尝试。"
                        )
                        log.warning("Convergence stalled for %d rounds, triggering honest exit", stall_threshold)
                    else:
                        system += (
                            f"\n\n## 待处理问题\n"
                            f"以下操作之前失败了，如果和当前任务相关，请尝试修复：\n"
                            f"{claims_text}"
                        )
                    log.info("Prober injected %d OPEN claims into prompt (stalled=%s)", len(open_claims), is_stalled)
            except Exception as e:
                log.warning("Prober injection failed: %s", e)

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
        # 文件引用注入到 user 消息
        user_content = user_input
        if file_context:
            user_content = f"{user_input}\n\n{file_context}"
        messages.append({"role": "user", "content": user_content})

        max_rounds = 20
        final_reply = ""

        # 探索账本：追踪信息饱和度，避免无限探索
        from educe.core.exploration_ledger import ExplorationLedger
        ledger = ExplorationLedger()

        # Runtime Facts: 动作账本聚合，注入模型上下文
        from educe.core.runtime_facts import RuntimeFacts
        runtime_facts = RuntimeFacts()
        runtime_facts.set_anchor(user_input)

        # Verify-Compile Loop: 轨迹收集器
        from educe.core.trace_compiler import TraceCollector
        trace_collector = TraceCollector()
        trace_collector.start(user_input)

        for round_idx in range(max_rounds):
            runtime_facts.advance_turn()
            self.effects.set_round(round_idx)
            # 注入态势感知（第二轮起）
            situation_text = self.effects.situation.render_for_model()
            if situation_text:
                messages.append({"role": "user", "content": situation_text})

            self._slog("framework", "turn_start",
                       summary=f"round {round_idx}",
                       data={"round": round_idx, "messages_len": len(messages)},
                       trace_payload=[m.get("content", "")[:200] for m in messages[-3:]],
                       trace_kind="messages")
            # 生命周期：model_called
            _prompt_chars = sum(len(m.get("content", "")) for m in messages)
            self._slog("lifecycle", "model_called",
                       summary=f"round={round_idx} prompt_chars={_prompt_chars} model={self.config.default_model.model}",
                       data={"round": round_idx, "prompt_chars": _prompt_chars,
                             "model": self.config.default_model.model, "messages_count": len(messages)})
            # 模型调用（action 轮次用非流式，避免标签被流式推送到前端）
            _t0 = __import__("time").time()
            try:
                raw = await asyncio.wait_for(client.chat(
                    messages=messages,
                    model=self.config.default_model.model,
                    max_tokens=self.config.default_model.max_tokens,
                ), timeout=120)
            except asyncio.TimeoutError:
                log.error("_action_loop | round %d model call timed out (120s)", round_idx)
                self._slog("llm_call", "llm_response", status="error",
                           summary="model call timed out",
                           data={"round": round_idx, "error": "timeout 120s"})
                self._emit_tool_event({
                    "type": "error",
                    "kind": "timeout",
                    "message": "模型响应超时(120s)，请稍后重试或换用更快的模型",
                    "retryable": True,
                })
                raw = ""
            except Exception as e:
                log.error("_action_loop | round %d model call failed: %s", round_idx, str(e)[:100])
                self._slog("llm_call", "llm_response", status="error",
                           summary=f"model call failed: {str(e)[:60]}",
                           data={"round": round_idx, "error": str(e)[:200]})
                self._emit_tool_event({
                    "type": "error",
                    "kind": "model_error",
                    "message": f"模型调用失败: {str(e)[:100]}",
                    "retryable": True,
                })
                raw = ""
            _llm_ms = (__import__("time").time() - _t0) * 1000

            # I/O Gateway: 模型调用 effect
            self.effects.emit("model",
                intent={"model": self.config.default_model.model, "prompt_chars": _prompt_chars},
                outcome={"response_len": len(raw) if raw else 0, "ms": round(_llm_ms),
                         "has_reply": bool(raw and not raw.strip().startswith("```"))})

            log.info("_action_loop | round=%d raw_len=%d", round_idx, len(raw) if raw else 0)

            if raw:
                usage_data = {}
                if hasattr(client, 'last_usage') and client.last_usage:
                    usage_data = client.last_usage
                self._slog("llm_call", "llm_response",
                           duration_ms=_llm_ms,
                           summary=f"round {round_idx}, {len(raw)} chars",
                           data={"round": round_idx, "raw_len": len(raw), **usage_data},
                           trace_payload=raw, trace_kind="llm_output")

            # 解析 action
            reply_text, actions = parse_actions(raw)
            # 生命周期：model_responded
            self._slog("lifecycle", "model_responded",
                       summary=f"round={round_idx} actions={len(actions)} chars={len(raw)} ms={_llm_ms:.0f}",
                       data={"round": round_idx, "actions_count": len(actions),
                             "action_types": [a.type for a in actions],
                             "raw_len": len(raw), "duration_ms": round(_llm_ms),
                             "reply_preview": reply_text[:150] if reply_text else "",
                             "action_params": [a.params[:60] for a in actions[:3]]})
            log.info("_action_loop | round=%d actions=%d reply_len=%d raw_tail='%s'",
                     round_idx, len(actions), len(reply_text),
                     raw[-200:].replace('\n', '\\n') if raw else "")
            log_activity(_sid, "model_output",
                        round=round_idx,
                        has_actions=len(actions),
                        action_types=[a.type for a in actions],
                        reply_preview=reply_text[:80])

            if actions:
                self._slog("framework", "actions_parsed",
                           summary=f"{len(actions)} actions: {[a.type for a in actions]}",
                           data={"count": len(actions), "types": [a.type for a in actions]})

                # 检测"读文件代替执行"：用户要求运行但模型用 read_file 看源码
                _EXEC_KW = ["运行", "执行", "跑一下", "run ", "execute"]
                if (round_idx == 0
                    and any(kw in user_input for kw in _EXEC_KW)
                    and actions[0].type in ("read_file", "read_lines")
                    and not any(a.type == "shell" for a in actions)):
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content":
                        "[系统] ⚠️ 用户要求的是实际运行脚本，不是读取源码。"
                        "read_file 看代码 ≠ 运行。请用 ```shell python 文件路径``` 真正执行脚本，"
                        "然后基于真实输出回答用户的问题。"})
                    log.info("_action_loop | round %d read-instead-of-run detected, forcing shell", round_idx)
                    self._slog("framework", "read_not_run",
                               summary=f"round {round_idx}, user asked exec but model used {actions[0].type}",
                               data={"action_types": [a.type for a in actions]})
                    continue

                # Shadow A/B: 记录 LLM 在反射命中情境下的实际决策
                shadow_input = self.context.metadata.pop("_shadow_reflex_input", None)
                if shadow_input and hasattr(self, '_reflex_router') and round_idx == 0:
                    llm_actions = [{"type": a.type, "params": getattr(a, 'params', '')} for a in actions[:3]]
                    self._reflex_router.record_llm_actual(shadow_input, llm_actions)

            if not actions:
                if not raw or not raw.strip():
                    log.warning("_action_loop | round %d empty response, messages=%d",
                                round_idx, len(messages))
                    if round_idx > 0:
                        fallback = "（分析完成，但生成回复时出现异常，请重试）"
                        self._notify_chunk("assistant", fallback)
                        final_reply = fallback
                        if hasattr(self, 'state'):
                            self.state.add_ai_reply(fallback)
                else:
                    for i in range(0, len(raw), 20):
                        self._notify_chunk("assistant", raw[i:i+20])
                    final_reply = raw
                    runtime_facts.record_reply()
                    if hasattr(self, 'state'):
                        self.state.add_ai_reply(raw)
                break

            # Irreversibility Gate: 唯一硬逻辑 — 不可逆动作前暂停
            from educe.core.irreversibility import is_irreversible

            def _needs_confirmation(action) -> bool:
                if self.context.metadata.get("_benchmark_auto_confirm"):
                    return False
                if is_irreversible(action):
                    return True
                # MCP connector 自声明的不可逆能力
                if action.type == "use_tool":
                    tool_name = action.name or ""
                    if "." in tool_name:
                        connector_name, capability_name = tool_name.split(".", 1)
                        connector = self._get_connector_registry().get(connector_name)
                        if connector and hasattr(connector, 'is_dangerous'):
                            return connector.is_dangerous(capability_name)
                return False

            pending_actions = [a for a in actions if _needs_confirmation(a)]
            immediate_actions = [a for a in actions if a not in pending_actions]

            # Phase 0 埋点：记录 confirm gate 决策
            for a in pending_actions:
                self.decision_ledger.record(
                    "confirm_gate", "framework",
                    f"require confirm: {a.type} {a.params[:80]}",
                    context={"action_type": a.type, "params": a.params[:200], "round": round_idx})
            for a in immediate_actions:
                self.decision_ledger.record(
                    "confirm_gate", "framework",
                    f"auto approve: {a.type} {a.params[:80]}",
                    context={"action_type": a.type, "params": a.params[:200], "round": round_idx})

            # 立即执行不需要确认的（recall、lookup_tools、use_tool）
            if immediate_actions:
                messages.append({"role": "assistant", "content": raw})
            for action in immediate_actions:
                # 阶段0: 通过 OutcomeCapturer 执行并记录因果
                capturer = self._get_outcome_capturer()
                action_meta = {"capability": action.name or action.type, "params": action.params[:200]}
                capture_context = {"user_input": user_input[:200], "phase": "action_loop", "round": round_idx}

                result = await capturer.capture(
                    session_id=_sid,
                    seed_id="default",
                    round_idx=round_idx,
                    decision_point=action.type,
                    context=capture_context,
                    action_meta=action_meta,
                    action_fn=lambda a=action: self._execute_action(a, user_input, transcript),
                )

                log_activity(_sid, "action_executed",
                            type=action.type,
                            success=result.get("success", False),
                            output_preview=result.get("output", "")[:80])
                runtime_facts.record_action(action.type, action.params, round_idx)
                output_str = result.get("output", "")
                self._slog("tool_call", "tool_result",
                           status="ok" if result.get("success") else "error",
                           summary=f"{action.type}: {'ok' if result.get('success') else 'fail'}",
                           data={"action_type": action.type, "action_name": action.name or "",
                                 "success": result.get("success", False), "round": round_idx},
                           trace_payload=output_str if len(output_str) > 500 else None,
                           trace_kind="tool_result")
                if hasattr(self, 'state'):
                    self.state.add_action_executed(
                        action.type, result.get("output", ""), result.get("success", False))

                # 推送富 action 卡片事件（所有 action 类型都发 action_detail）
                _action_summary = self._build_action_summary(action, result)
                if _action_summary and transcript:
                    transcript.add("action", "system", _action_summary["label"],
                                   elapsed=_action_summary.get("elapsed", 0))
                    import json as _json_act
                    _detail_evt = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                        content="__TOOL_EVENT__" + _json_act.dumps({
                            "event": "action_detail",
                            "action_type": action.type,
                            "name": action.type if action.type != "use_tool" else (action.name or action.type),
                            "summary": _action_summary.get("command", "") or _action_summary["label"],
                            "label": _action_summary["label"],
                            "command": _action_summary.get("command", ""),
                            "output_preview": _action_summary.get("output_preview", ""),
                            "success": result.get("success", False),
                            "elapsed_ms": _action_summary.get("elapsed_ms", 0),
                            "retried": _action_summary.get("retried", False),
                        }, ensure_ascii=False))
                    self._notify(_detail_evt)

                # IterationState: 将执行结果映射为知识状态更新
                self._update_iteration_state(action, result, _sid)

                # Clarify: 模型主动向用户提问 → 暂停循环
                if result.get("_clarify"):
                    question = result.get("output", "")
                    self._notify_chunk("assistant", question)
                    if hasattr(self, 'state'):
                        self.state.add_ai_reply(question)
                    self.conversation.add_assistant(question)
                    # 保存上下文供用户回复后续接
                    self.context.metadata["_clarify_pending"] = True
                    self.context.metadata["_pending_user_input"] = user_input
                    self._slog("framework", "clarify_pause",
                               summary=f"asking: {question[:80]}",
                               data={"question": question[:200]})
                    final_reply = question
                    break
                if not result.get("success"):
                    self.context.metadata.setdefault("_failed_actions", []).append({
                        "type": action.type, "params": action.params[:200],
                        "reason": result.get("output", "")[:200], "round": round_idx,
                    })
                    # Verify-Compile Loop: 失败反思注入 — 引导模型分析原因并调整
                    fail_output = result.get("output", "")[:800]
                    messages.append({"role": "user", "content":
                        f"[系统] ⚠️ 操作失败。请分析原因并调整方案：\n"
                        f"失败操作: {action.type} {action.params[:100]}\n"
                        f"错误信息: {fail_output}\n"
                        f"请判断：(1)环境缺失(缺依赖/权限)→尝试修复 (2)方案错误→换方向 (3)不可恢复→告知用户"
                    })
                elif self.context.metadata.get("_failed_actions"):
                    failed = self.context.metadata["_failed_actions"][-1]
                    asyncio.create_task(self._learn_from_retry(
                        failed_action=f"{failed['type']}:{failed['params']}",
                        failure_reason=failed["reason"],
                        success_action=f"{action.type}:{action.params[:200]}",
                        context=user_input,
                    ))
                    self.context.metadata.pop("_failed_actions", None)
                # tool_event 状态行（所有 action 类型均推送）
                tool_desc = action.type
                if action.type == "use_tool" and action.name:
                    tool_desc = f"use_tool: {action.name}"
                success_icon = "✓" if result.get("success") else "✗"
                self._notify(Message(
                    type=MessageType.RESULT, sender="system", receiver="user",
                    content=f"{success_icon} {tool_desc}",
                    metadata={"event": "tool_event", "tool_type": action.type,
                              "tool_name": action.name, "success": result.get("success", False)}
                ))
                # Action 结果推送为独立事件（不混入 assistant 对话流）
                # shell 已有 ToolStreamCard 流式展示，仅推送 read_dir/read_file/search_in_file 等非流式结果
                if action.type in ("read_dir", "read_file", "read_lines", "search_in_file") and result.get("output"):
                    import json as _json_ar
                    output_preview = result["output"][:2000]
                    _ar_evt = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                        content="__TOOL_EVENT__" + _json_ar.dumps({
                            "event": "action_result",
                            "action_type": action.type,
                            "name": action.type,
                            "summary": action.params.strip()[:60],
                            "output": output_preview,
                            "success": result.get("success", False),
                        }, ensure_ascii=False))
                    self._notify(_ar_evt)
                messages.append({"role": "user", "content":
                    f"[系统] {'✓' if result.get('success') else '✗'} {action.type} 结果：{result.get('output', '')[:500]}"})

                # 探索账本：记录行为
                ledger.record(action.type, action.params, result.get("output", ""), result.get("success", False))
                # Verify-Compile Loop: 记录轨迹
                trace_collector.record(action.type, action.params,
                                       result.get("output", ""), result.get("success", False))
            if immediate_actions and reply_text and not pending_actions:
                for i in range(0, len(reply_text), 20):
                    self._notify_chunk("assistant", reply_text[i:i+20])
                self.conversation.add_assistant(reply_text)
                runtime_facts.record_reply()
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
                    elif a.type == "shell":
                        item["display"] = f"执行命令：{a.params[:120]}"
                    elif a.type == "write_file":
                        try:
                            parsed = _json.loads(a.params)
                            item["display"] = f"写入文件：{parsed.get('path', a.params[:60])}"
                        except Exception:
                            item["display"] = f"写入文件：{a.params[:60]}"
                    elif a.type == "plan":
                        try:
                            parsed = _json.loads(a.params)
                            steps = parsed.get("steps", [])
                            item["display"] = f"执行计划（{len(steps)}步）：{' → '.join(s[:15] for s in steps[:4])}"
                        except Exception:
                            item["display"] = f"执行计划：{a.params[:80]}"
                    confirm_items.append(item)

                # 暂存到 context，等用户确认
                self.context.metadata["_pending_actions"] = confirm_items
                self.context.metadata["_pending_user_input"] = user_input

                # record blocked actions for runtime_facts
                for a in pending_actions:
                    runtime_facts.record_blocked(a.type, a.params, round_idx)

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

            # Output-Metric Attribution: 记录输出特征到对应 units
            self._record_output_metrics(final_reply)

        reason = "no_action" if final_reply else "max_rounds"
        if self.context.metadata.get("_clarify_pending"):
            reason = "clarify"

        # 阶段2: CompositeSkill activation 反馈
        activated_ids = self.context.metadata.get("_activated_skill_ids", [])
        if activated_ids:
            has_errors = any(
                e.get("status") == "error"
                for e in (self.context.metadata.get("_failed_actions") or [])
            )
            success = (reason == "no_action" and not has_errors)
            try:
                registry = self._get_skill_registry()
                for sid in activated_ids:
                    registry.record_activation(sid, success=success)
            except Exception as e:
                log.debug("skill activation recording failed: %s", e)

        self._slog("framework", "turn_end",
                   summary=f"ended: {reason}",
                   data={"reason": reason})

        # ═══ 记忆自动写入：fact / scar ═══
        trace_summary = trace_collector.get_summary()
        if trace_summary and trace_summary["steps"] >= 2:
            if trace_summary["all_success"]:
                self._auto_write_memory(
                    "fact",
                    f"{trace_summary['user_input'][:80]} → {trace_summary['action_chain']}",
                    scope=self.context.metadata.get("_project_context_path", ""),
                    detail_key=trace_summary["action_chain"],
                )
            elif trace_summary["had_failures"] and trace_summary["recovered"]:
                failure_hint = trace_summary["failure_outputs"][0][:80] if trace_summary["failure_outputs"] else "unknown"
                self._auto_write_memory(
                    "scar",
                    f"When: {trace_summary['user_input'][:60]}. Issue: {failure_hint}. Recovered via retry.",
                    scope=self.context.metadata.get("_project_context_path", ""),
                    detail_key=f"fail:{failure_hint[:40]}",
                )

        # Verify-Compile Loop: 尝试编译成功轨迹为 skill
        compiled_skill = trace_collector.finish()
        if compiled_skill:
            try:
                registry = self._get_skill_registry()
                from educe.core.metabolism.composite_skill import CompositeSkill
                skill = CompositeSkill.from_dict(compiled_skill)
                registry.register(skill)
                log.info("TraceCompiler: registered skill '%s'", skill.name)
            except Exception as e:
                log.debug("TraceCompiler register failed: %s", e)

        # 器官信号检测（冷路径）
        if self.organ_registry and final_reply:
            self.organ_registry.observe_all(user_input, ai_reply_len=len(final_reply))
            try:
                await self.organ_registry.check_all()
            except Exception as e:
                log.debug("organ check_all error: %s", e)

        return self.context

    async def _execute_action(self, action, user_input: str, transcript) -> dict:
        """执行单个 action，返回结果 dict。Guardian 在此拦截/改写。"""
        from educe.core.action_executor import ParsedAction
        import json as _json
        _sid = self.context.metadata.get("session_id", "")

        # Action Normalizer: 框架识别自己的动词，无论模型用什么语法调用
        # 模型可能用 use_tool read_lines 或 use_tool filesystem.search_in_file
        # 统一归一化到内置 action type
        BUILTIN_ACTIONS = {"shell", "read_dir", "read_file", "write_file",
                           "edit_file", "search_in_file", "read_lines",
                           "memorize", "build", "plan", "recall", "lookup_tools"}
        if action.type == "use_tool" and action.name:
            # 处理 "filesystem.search_in_file" → "search_in_file"
            effective_name = action.name.split(".")[-1] if "." in action.name else action.name
            # 处理常见别名: search_files → search_in_file, file_edit → edit_file
            _TOOL_ALIASES = {
                "search_files": "search_in_file",
                "search": "search_in_file",
                "file_edit": "edit_file",
                "file_read": "read_file",
                "file_write": "write_file",
                "read": "read_file",
                "write": "write_file",
                "edit": "edit_file",
                "execute": "shell",
                "run_command": "shell",
                "list_dir": "read_dir",
                "list_directory": "read_dir",
            }
            effective_name = _TOOL_ALIASES.get(effective_name, effective_name)
            if effective_name in BUILTIN_ACTIONS:
                # 参数归一化：JSON → 内置纯文本格式
                normalized_params = self._normalize_tool_params(effective_name, action.params)
                action = ParsedAction(type=effective_name, params=normalized_params, name="")

        # 执行层守卫：检查并可能改写 action
        guardian = self._get_guardian()
        guard_result = guardian.check(action.type, action.params)
        if guard_result.action == "rewrite":
            action = ParsedAction(
                type=guard_result.new_type,
                params=guard_result.new_params,
                name=action.name,
            )
        elif guard_result.action == "block":
            return {"success": False, "output": f"[Guardian 拦截] {guard_result.reason}"}

        if action.type == "clarify":
            return {"success": True, "output": action.params.strip(),
                    "_clarify": True}
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

        elif action.type == "shell":
            return await self._exec_shell(action, _sid)

        elif action.type == "read_dir":
            return await self._exec_read_dir(action)

        elif action.type == "read_file":
            return await self._exec_read_file(action, _sid)

        elif action.type == "write_file":
            return await self._exec_write_file(action, _sid)

        elif action.type == "edit_file":
            return await self._exec_edit_file(action, _sid)

        elif action.type == "search_in_file":
            return await self._exec_search_in_file(action, _sid)

        elif action.type == "read_lines":
            return await self._exec_read_lines(action, _sid)

        elif action.type == "plan":
            return await self._exec_plan(action, _sid)

        elif action.type == "recall":
            return await self._exec_recall(action, _sid)

        elif action.type == "lookup_tools":
            connector_name = action.params.strip() if action.params else ""
            if connector_name:
                detail = await self._get_connector_registry().get_level2_description(connector_name)
                return {"success": True, "output": detail}
            else:
                summary = self._get_connector_registry().get_level1_descriptions()
                return {"success": True, "output": f"可用连接器：\n{summary}"}

        elif action.type == "use_tool":
            return await self._exec_use_tool(action)

        else:
            return {"success": False, "output": f"未知操作: {action.type}"}


    async def _handle_action_confirm(self, user_input: str, pending: list) -> "WorkContext":
        """处理用户对待确认 action 的回应（确认/补充/取消）"""
        from educe.core.action_executor import ParsedAction
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
            from educe.core.transcript import TaskTranscript
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
                from educe.core.transcript import TaskTranscript
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
                # 推送 action_detail 事件（与主循环一致）
                _action_summary = self._build_action_summary(action, result)
                if _action_summary:
                    import json as _json_cfm
                    _cfm_evt = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                        content="__TOOL_EVENT__" + _json_cfm.dumps({
                            "event": "action_detail",
                            "action_type": action.type,
                            "name": action.type if action.type != "use_tool" else (action.name or action.type),
                            "summary": _action_summary.get("command", "") or _action_summary["label"],
                            "label": _action_summary["label"],
                            "command": _action_summary.get("command", ""),
                            "output_preview": _action_summary.get("output_preview", ""),
                            "success": result.get("success", False),
                            "elapsed_ms": _action_summary.get("elapsed_ms", 0),
                            "retried": _action_summary.get("retried", False),
                        }, ensure_ascii=False))
                    self._notify(_cfm_evt)
                # 非流式工具推送 action_result
                if action.type in ("read_dir", "read_file", "read_lines", "search_in_file") and result.get("output"):
                    import json as _json_cfm_ar
                    _cfm_ar_evt = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                        content="__TOOL_EVENT__" + _json_cfm_ar.dumps({
                            "event": "action_result",
                            "action_type": action.type,
                            "name": action.type,
                            "summary": action.params.strip()[:60],
                            "output": result["output"][:2000],
                            "success": result.get("success", False),
                        }, ensure_ascii=False))
                    self._notify(_cfm_ar_evt)
                if result.get("output"):
                    self.conversation.add_assistant(result["output"][:1000])

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
        return self._get_tool_registry().get_descriptions()

    def _get_tool_registry(self):
        if not hasattr(self, '_tool_registry'):
            from educe.core.tool_registry import ToolRegistry
            self._tool_registry = ToolRegistry()
            from pathlib import Path
            self._tool_registry.load_from_config(Path(".educe/tools.json"))
        return self._tool_registry

    def _get_connector_registry(self):
        """获取 ConnectorRegistry（包含 builtin tools + MCP servers）"""
        if not hasattr(self, '_connector_registry'):
            from educe.core.connector import ConnectorRegistry
            from educe.core.connectors.builtin import BuiltinConnector
            from educe.core.connectors.mcp import load_mcp_connectors
            from pathlib import Path

            registry = ConnectorRegistry()
            # 包装现有 ToolRegistry
            registry.register(BuiltinConnector(self._get_tool_registry()))
            # 加载 MCP 连接器
            for mcp in load_mcp_connectors(Path(".educe/mcp.json")):
                registry.register(mcp)

            self._connector_registry = registry
        return self._connector_registry

    def _get_outcome_capturer(self):
        """获取 OutcomeCapturer（因果账本写入器）"""
        if not hasattr(self, '_outcome_capturer'):
            from educe.core.metabolism.ledger import LedgerStore
            from educe.core.metabolism.capturer import OutcomeCapturer
            from pathlib import Path
            ledger = LedgerStore(Path(".educe/metabolism"))
            self._outcome_capturer = OutcomeCapturer(ledger)
        return self._outcome_capturer

    def _get_causal_retriever(self):
        """获取因果检索器（决策前检索历史经验）"""
        if not hasattr(self, '_causal_retriever'):
            from educe.core.metabolism.retriever import CausalRetriever
            from educe.core.metabolism.ledger import LedgerStore
            from pathlib import Path
            ledger = LedgerStore(Path(".educe/metabolism"))
            self._causal_retriever = CausalRetriever(ledger)
        return self._causal_retriever

    def _get_skill_registry(self):
        """获取 CompositeSkill 注册表"""
        if not hasattr(self, '_skill_registry'):
            from educe.core.metabolism.composite_skill import SkillRegistry
            from pathlib import Path
            self._skill_registry = SkillRegistry(Path(".educe/skills"))
        return self._skill_registry

    def _get_evolution_bus(self):
        """获取 EvolutionEvent 总线 + FrontendProjection"""
        if not hasattr(self, '_evolution_bus'):
            from educe.core.evolution_bus import EvolutionBus, EvolutionKind
            self._evolution_bus = EvolutionBus()

            async def frontend_projection(event):
                """将 PROPOSE/CRYSTALLIZE/reflex_hit 推送到前端"""
                if event.kind == EvolutionKind.PROPOSE:
                    self._emit_tool_event({
                        "type": "evolution_propose",
                        "event_id": event.event_id,
                        "organ": event.organ.to_dict(),
                        "phrase": event.phrase,
                        "cause": event.cause,
                        "confidence": event.confidence,
                        "delta": event.delta,
                    })
                elif event.kind == EvolutionKind.CRYSTALLIZE:
                    self._emit_tool_event({
                        "type": "evolution_crystallize",
                        "event_id": event.event_id,
                        "organ": event.organ.to_dict(),
                        "phrase": event.phrase,
                        "confidence": event.confidence,
                    })
                elif event.kind == EvolutionKind.SHIFT and event.organ.family in ("reflex", "verbosity"):
                    self._emit_tool_event({
                        "type": "reflex_bubble",
                        "event_id": event.event_id,
                        "organ": event.organ.to_dict(),
                        "phrase": event.phrase,
                    })

            self._evolution_bus.subscribe(frontend_projection)
        return self._evolution_bus

    @staticmethod
    def _build_action_summary(action, result: dict) -> dict | None:
        """构建 action 的富摘要（Round 12：过程透明 Glance 层）"""
        output = result.get("output", "")
        success = result.get("success", False)
        action_type = action.type

        if action_type == "shell":
            # 从输出中提取命令（格式: "$ cmd\n[cwd: .]\noutput\n[exit: N]"）
            lines = output.split("\n")
            cmd_line = ""
            for l in lines:
                if l.startswith("$ "):
                    cmd_line = l[2:].strip()
                    break
            # 提取命令的"宾语"
            cmd_short = cmd_line.split("|")[0].strip()[:60] if cmd_line else action.params[:60]
            # 输出摘要：取第一行有意义的输出
            output_lines = [l for l in lines if l.strip() and not l.startswith("$") and not l.startswith("[")]
            preview = output_lines[0][:80] if output_lines else ""
            return {
                "label": f"{'✓' if success else '✗'} {cmd_short}",
                "command": cmd_line,
                "output_preview": preview,
                "elapsed_ms": 0,
                "retried": "[🔧 器官修复]" in output,
            }

        elif action_type in ("read_file", "read_lines", "read_dir"):
            target = action.params.strip()[:50]
            return {
                "label": f"{'✓' if success else '✗'} 读取 {target}",
                "command": f"{action_type} {target}",
                "output_preview": output[:80] if output else "",
            }

        elif action_type == "write_file":
            # 从 params 提取文件路径
            path = ""
            if "path:" in action.params:
                path = action.params.split("path:")[1].split("\n")[0].strip()[:50]
            elif action.params.strip().startswith("{"):
                import json as _j
                try:
                    path = _j.loads(action.params).get("path", "")[:50]
                except Exception as e:
                    log.debug("suppressed: %s", e)
            return {
                "label": f"{'✓' if success else '✗'} 写入 {path or '文件'}",
                "command": f"write_file {path}",
                "output_preview": "",
            }

        elif action_type == "edit_file":
            return {
                "label": f"{'✓' if success else '✗'} 编辑文件",
                "command": "edit_file",
                "output_preview": output[:60] if output else "",
            }

        elif action_type == "search_in_file":
            return {
                "label": f"{'✓' if success else '✗'} 搜索 {action.params.strip()[:40]}",
                "command": f"search_in_file {action.params.strip()[:60]}",
                "output_preview": output[:80] if output else "",
            }

        else:
            return {
                "label": f"{'✓' if success else '✗'} {action_type}",
                "command": action.params[:60] if action.params else "",
                "output_preview": output[:60] if output else "",
            }

    def _get_knowledge_signals(self) -> dict:
        """加载知识蒸馏与领域检测的声明式配置（公理五）"""
        if not hasattr(self, '_knowledge_signals'):
            from pathlib import Path
            paths = [
                Path(".educe/config/knowledge_signals.yaml"),
                Path(__file__).parent.parent / "config" / "knowledge_signals.yaml",
            ]
            self._knowledge_signals = {}
            for p in paths:
                if p.exists():
                    try:
                        import yaml
                        self._knowledge_signals = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                        break
                    except Exception as e:
                        log.debug("knowledge_signals yaml parse failed: %s", e)
        return self._knowledge_signals

    async def _try_reflex(self, user_input: str) -> str | None:
        """阶段3: ReflexRouter 尝试反射执行。
        返回 None = handled（已短路），str = 降级提示，"" = passthrough。

        多任务请求不短路——反射只处理单一明确的 readonly 请求。
        Shadow mode 时：handled 不短路，记录到 shadow_ab.jsonl 供后续对比。
        """
        # 多任务检测：包含枚举模式的请求不走反射
        if any(marker in user_input for marker in ["1)", "2)", "3)", "第一", "第二", "第三", "首先", "然后", "最后"]):
            return ""

        try:
            from educe.core.metabolism.reflex_router import ReflexRouter
            if not hasattr(self, '_reflex_router'):
                import os
                shadow = os.environ.get("EDUCE_REFLEX_SHADOW", "0") == "1"
                self._reflex_router = ReflexRouter(self._get_skill_registry(), shadow=shadow)
            result = await self._reflex_router.try_reflex(user_input)

            # Shadow mode: 反射输出已记录，不短路
            if result.shadow_record:
                self._slog("framework", "reflex_shadow",
                           summary=f"shadow hit: skill={result.skill_id}",
                           data=result.shadow_record)
                self.context.metadata["_shadow_reflex_input"] = user_input
                return ""

            if result.handled:
                self.decision_ledger.record(
                    "reflex_bypass", "framework",
                    f"skip LLM, direct execute skill={result.skill_id}",
                    context={"skill_id": result.skill_id, "input": user_input[:200]})
                self._slog("framework", "reflex_hit",
                           summary=f"reflex bypassed LLM, skill={result.skill_id}",
                           data={"skill_id": result.skill_id, "response_len": len(result.response)})
                msg = Message(type=MessageType.RESULT, sender="assistant",
                              receiver="user", content=result.response)
                self.context.add_message(msg)
                self._notify(msg)
                self.conversation.add_assistant(result.response)
                return None  # 信号：已短路
            if result.escalation_hint:
                return result.escalation_hint
        except Exception as e:
            log.debug("reflex check failed: %s", e)
        return ""

    def _match_composite_skills(self, user_input: str, round_idx: int = 0) -> str:
        """匹配已编译的 CompositeSkill，返回注入文本"""
        try:
            from educe.core.metabolism.context_sig import task_type
            registry = self._get_skill_registry()
            if registry.count == 0:
                return ""

            scope = task_type(user_input)
            is_start = (round_idx == 0)
            matched = registry.match(scope, is_start=is_start)

            if not matched:
                return ""

            # 相关性过滤：只注入与 user_input 动词相关的 skill
            relevant = self._filter_relevant_skills(matched, user_input)
            if not relevant:
                return ""

            # 最多注入 2 个最相关的 skill（节省 prompt token）
            top_skills = relevant[:2]

            # 按最高 level 选择渲染模式
            best = top_skills[0]
            if best.level >= 2:
                # L2+: Plan-Graph 模式 — LLM 一次性审批
                lines = ["\n\n## 执行计划（一次性审批）\n"]
                lines.append(best.render_plan_graph())
                lines.append("\n如果计划合适，请直接按步骤输出所有 action。如需调整参数，修改后输出。")
            else:
                # L0/L1: 提示/模板模式
                lines = ["\n\n## 已掌握的多步技能（可一口气执行）\n"]
                for skill in top_skills:
                    lines.append(skill.render_for_prompt())
                    lines.append("")

            # 记录本轮激活的 skill ids
            self.context.metadata["_activated_skill_ids"] = [s.skill_id for s in top_skills]

            self._slog("framework", "skill_matched",
                       summary=f"matched {len(top_skills)} skills for scope={scope} (L{best.level})",
                       data={"scope": scope, "skill_names": [s.name for s in top_skills],
                             "best_level": best.level, "is_start": is_start})

            return "\n".join(lines)
        except Exception as e:
            log.debug("composite skill match failed: %s", e)
            return ""
        """根据 skill 自声明的 trigger_keywords 过滤相关性（公理五：认知来自声明）"""
        lower = user_input.lower()
        relevant = []
        for skill in skills:
            keywords = skill.trigger_keywords
            if not keywords or any(kw in lower for kw in keywords):
                relevant.append(skill)
        return relevant

    def _l1_clarification_check(self, user_input: str) -> str | None:
        """L1 澄清：检测不可逆高危意图，要求用户确认方向。

        不做模糊度判断（那是模型的事）。只检测客观的高危信号。
        返回 None 表示不需要澄清，返回字符串表示澄清消息。
        """
        text = user_input.lower().strip()

        # 高危模式：不可逆操作 + 缺乏具体目标
        # 注意：编程上下文中的"删除"（如"删除偶数"）不应触发
        HIGH_RISK_PATTERNS = [
            (["删除所有文件", "删除全部文件", "删除所有数据", "rm -rf", "清空数据库", "清空目录"], "删除操作不可逆"),
            (["部署到生产", "部署到线上", "deploy to prod"], "生产部署影响线上用户"),
            (["推送到 main", "push to main", "force push"], "推送到主分支影响团队"),
            (["格式化磁盘", "格式化硬盘", "格式化分区", "重装系统", "初始化数据库"], "数据可能丢失"),
        ]

        for keywords, risk_desc in HIGH_RISK_PATTERNS:
            if any(kw in text for kw in keywords):
                return (
                    f"⚠️ 检测到高危操作（{risk_desc}）。\n\n"
                    f"请确认你的意图：具体要对什么执行这个操作？\n"
                    f"确认后我再执行，或者告诉我更具体的范围。"
                )

        return None

    def _get_iteration_state(self, session_id: str):
        """获取当前 session 的 IterationState + StateLog"""
        if not hasattr(self, '_iteration_state'):
            from educe.core.iteration_state import IterationState, StateLog
            from pathlib import Path
            log_path = Path(f".educe/convergence/{session_id[:16]}.jsonl")
            state_log = StateLog(log_path)
            state_log.load()
            if state_log.latest():
                state = state_log.latest()
            else:
                state = IterationState(task_id=session_id)
            self._iteration_state = state
            self._iteration_state_log = state_log
        return self._iteration_state, self._iteration_state_log

    def _update_iteration_state(self, action, result: dict, session_id: str):
        """将 action 执行结果映射为 IterationState 的 Claim 更新"""
        from educe.core.iteration_state import Claim, FactStatus
        state, log = self._get_iteration_state(session_id)

        output = result.get("output", "")[:200]
        success = result.get("success", False)
        evidence = (f"{action.type}:{session_id[:8]}:{state.revision}",)

        if action.type == "write_file" and success:
            claim = Claim.new(f"file created: {action.params.split(chr(10))[0][:60]}",
                              FactStatus.VERIFIED, evidence)
        elif action.type == "edit_file" and success:
            claim = Claim.new(f"edit applied: {action.params.split(chr(10))[0][:60]}",
                              FactStatus.VERIFIED, evidence)
        elif action.type == "edit_file" and not success:
            claim = Claim.new(f"edit failed: {output[:60]}",
                              FactStatus.OPEN, evidence)
        elif action.type == "shell" and success:
            claim = Claim.new(f"command succeeded: {action.params[:60]}",
                              FactStatus.VERIFIED, evidence)
            # Prober: 同命令之前失败 → 现在成功 = 关闭旧 OPEN claim
            failed_text = f"command failed: {action.params[:60]}"
            failed_claim_id = Claim.new(failed_text).claim_id
            if failed_claim_id in state.claims and state.claims[failed_claim_id].status == FactStatus.OPEN:
                closed = state.claims[failed_claim_id].with_status(
                    FactStatus.RULED_OUT, ("resolved_by_success",) + evidence)
                state = state.apply(closed)
        elif action.type == "shell" and not success:
            claim = Claim.new(f"command failed: {action.params[:60]}",
                              FactStatus.OPEN, evidence)
        elif action.type in ("read_file", "read_dir") and success:
            claim = Claim.new(f"observed: {action.params[:60]}",
                              FactStatus.VERIFIED, evidence)
        else:
            return

        state = state.apply(claim)
        log.record(state)
        self._iteration_state = state

    def _get_guardian(self):
        """获取执行层守卫"""
        if not hasattr(self, '_guardian'):
            from educe.core.metabolism.guardian import ActionGuardian
            from educe.core.metabolism.ledger import LedgerStore
            from pathlib import Path
            ledger = LedgerStore(Path(".educe/metabolism"))
            self._guardian = ActionGuardian(ledger)
        return self._guardian

    def _get_process_supervisor(self):
        """获取进程监管器（session 级别后台进程管理）"""
        if not hasattr(self, '_process_supervisor'):
            from educe.core.process_supervisor import ProcessSupervisor
            self._process_supervisor = ProcessSupervisor()
            self._process_supervisor.start_watchdog()
        return self._process_supervisor

    @staticmethod
    def _is_pip_installable(pkg: str) -> bool:
        """检查包名是否可通过 pip 安装（运行时探测 stdlib，公理五合规）"""
        import sys
        # 用 Python 自身的 stdlib_module_names（运行时事实，不硬编码）
        if hasattr(sys, 'stdlib_module_names'):
            if pkg in sys.stdlib_module_names:
                return False
        # 子模块也检查（如 importlib.metadata → importlib 是 stdlib）
        top_level = pkg.split(".")[0]
        if hasattr(sys, 'stdlib_module_names') and top_level in sys.stdlib_module_names:
            return False
        return True

    async def _try_organ(
        self, cmd: str, full_output: str, exit_code: int, work_dir, session_id: str
    ) -> dict | None:
        """
        阶段4: 器官系统 — 根据错误模式匹配器官并执行反馈环。

        通用化：不再硬编码 ModuleNotFoundError，而是用 OrganRegistry 匹配。
        """
        try:
            from educe.core.metabolism.organ import OrganExecutor, OrganRegistry

            if not hasattr(self, '_organ_registry'):
                self._organ_registry = OrganRegistry()

            organ = self._organ_registry.match(full_output, exit_code)
            if not organ:
                return None

            executor = OrganExecutor(organ)
            state = executor.start({"cmd": cmd})

            # 第一步已执行（触发此方法的那次），直接 advance
            executor.advance(state, output=full_output, exit_code=exit_code)

            if state.current_node == "escalate" or state.is_done:
                return None

            # 预检查：提取的包名是否可 pip 安装？
            pkg = state.variables.get("pkg", "")
            if pkg and not self._is_pip_installable(pkg):
                log.info(f"Organ skip: '{pkg}' is not pip-installable (stdlib or known-bad)")
                return None

            import asyncio as _aio, os as _os
            env = {**_os.environ, "PATH": _os.environ.get("PATH", "")}
            steps_log = []

            # 通用执行循环：沿图遍历直到终态
            while not state.is_done and state.iteration < state.max_iterations:
                action = executor.get_next_action(state)
                if not action:
                    break
                if action["action_type"] != "shell":
                    break

                step_cmd = action["command"]
                log.info(f"Organ '{organ.name}' step: {step_cmd}")

                proc = await _aio.create_subprocess_shell(
                    step_cmd, cwd=str(work_dir), env=env,
                    stdout=_aio.subprocess.PIPE, stderr=_aio.subprocess.PIPE,
                )
                stdout, stderr = await _aio.wait_for(proc.communicate(), timeout=60)
                step_output = stdout.decode(errors="ignore") + stderr.decode(errors="ignore")
                steps_log.append((step_cmd, proc.returncode, step_output[:500]))

                executor.advance(state, output=step_output, exit_code=proc.returncode)

            if not steps_log:
                return None

            # 构造输出日志
            last_cmd, last_exit, last_output = steps_log[-1]
            vars_str = ", ".join(f"{k}={v}" for k, v in state.variables.items())
            repair_log = f"$ {cmd}\n[cwd: .]\n[🔧 器官修复] {organ.name}\n"
            for s_cmd, s_exit, s_out in steps_log:
                status = "成功" if s_exit == 0 else "失败"
                repair_log += f"  → {s_cmd}: {status}\n"
            repair_log += f"\n{last_output[:3000] or '（无输出）'}\n[exit: {last_exit}]"

            self._slog("framework", "organ_execute",
                       summary=f"organ '{organ.name}': {len(steps_log)} steps, final_exit={last_exit}",
                       data={"organ_id": organ.organ_id, "steps": len(steps_log),
                             "variables": state.variables, "final_exit": last_exit})

            return {
                "success": last_exit == 0,
                "output": repair_log,
            }

        except Exception as e:
            log.warning(f"Organ execution failed: {e}")
            return None
            return None

    def _get_behavior_manifest(self):
        """获取 BehaviorManifest（Agent 行为仓库）"""
        if not hasattr(self, '_behavior_manifest'):
            from educe.core.behavior import BehaviorManifest
            from pathlib import Path
            manifest_path = Path(".educe/behavior/manifest.json")
            if manifest_path.exists():
                self._behavior_manifest = BehaviorManifest.load(manifest_path)
            else:
                self._behavior_manifest = BehaviorManifest(
                    agent_id="default",
                    base_seed="",
                )
        return self._behavior_manifest

    def _get_behavior_learner(self):
        """获取 BehaviorLearner（行为学习器）"""
        if not hasattr(self, '_behavior_learner'):
            from educe.core.behavior_learner import BehaviorLearner
            from pathlib import Path
            manifest = self._get_behavior_manifest()
            self._behavior_learner = BehaviorLearner(
                manifest=manifest,
                persist_path=Path(".educe/behavior/manifest.json"),
            )
        return self._behavior_learner

    async def _learn_from_correction(self, prev_response: str, user_correction: str):
        """后台异步：从用户纠正中提取行为规则"""
        try:
            client = self._get_client()
            if not client:
                return
            learner = self._get_behavior_learner()
            unit = await learner.learn_from_correction(
                prev_response=prev_response,
                user_correction=user_correction,
                client=client,
                model=self.config.default_model.model,
            )
            if unit:
                _sid = self.context.metadata.get("session_id", "")
                log_activity(_sid, "behavior_learned",
                            trigger=unit.trigger[:60],
                            directive=unit.directive[:60],
                            source="correction")
        except Exception as e:
            log.warning("_learn_from_correction failed: %s", str(e)[:100])

    async def _learn_from_retry(self, failed_action: str, failure_reason: str,
                                success_action: str, context: str):
        """后台异步：从失败→成功模式中提取行为规则"""
        try:
            client = self._get_client()
            if not client:
                return
            learner = self._get_behavior_learner()
            unit = await learner.learn_from_retry(
                failed_action=failed_action,
                failure_reason=failure_reason,
                success_action=success_action,
                context=context,
                client=client,
                model=self.config.default_model.model,
            )
            if unit:
                _sid = self.context.metadata.get("session_id", "")
                log_activity(_sid, "behavior_learned",
                            trigger=unit.trigger[:60],
                            directive=unit.directive[:60],
                            source="retry")
        except Exception as e:
            log.warning("_learn_from_retry failed: %s", str(e)[:100])

    def _record_output_metrics(self, response: str):
        """计算回复特征并记录到对应 units（Output-Metric Attribution）"""
        try:
            from educe.core.response_features import compute_response_features
            features = compute_response_features(response)

            manifest = self._get_behavior_manifest()
            injected_ids = self.context.metadata.get("_matched_behavior_units", [])
            withheld_ids = self.context.metadata.get("_withheld_behavior_units", [])

            for uid in injected_ids:
                unit = manifest.get_unit(uid)
                if unit and unit.effect_dimension and unit.effect_dimension in features:
                    unit.record_metric_sample(features[unit.effect_dimension], injected=True)

            for uid in withheld_ids:
                unit = manifest.get_unit(uid)
                if unit and unit.effect_dimension and unit.effect_dimension in features:
                    unit.record_metric_sample(features[unit.effect_dimension], injected=False)
        except Exception as e:
            log.debug("_record_output_metrics: %s", str(e)[:80])

    # ═══════════════════════════════════════
    #  Builder → Tester → 循环（优化版）
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
        except Exception as e:
            log.debug("knowledge extraction failed: %s", e)

    def _match_skill(self, user_input: str) -> str | None:
        try:
            from educe.skills.builtin_skills import match_skill
            skill = match_skill(user_input)
            if skill and skill.get("prompt_template"):
                return skill["prompt_template"]
        except Exception as e:
            log.debug("builtin skill match failed: %s", e)
        from educe.skills.registry import SkillRegistry
        try:
            sr = SkillRegistry(".educe/skills", ".educe/community_skills")
            results = sr.search(user_input)
            if results and results[0].prompt_template:
                return results[0].prompt_template
        except Exception as e:
            log.debug("skill registry search failed: %s", e)
        return None

    def _extract_and_store_knowledge(self, question: str, response: str, domain: str):
        """从高质量回答中提取知识点存入知识库——越用越强的核心"""
        import re
        if not self.knowledge or len(response) < 100:
            return

        insight_markers = self._get_knowledge_signals().get("insight_markers", [])
        pattern = "|".join(re.escape(m) for m in insight_markers) if insight_markers else r"本质|核心|关键"

        sentences = re.split(r'[。\n]', response)
        valuable = []
        for s in sentences:
            s = s.strip()
            if len(s) < 15 or len(s) > 150:
                continue
            if re.search(pattern, s):
                valuable.append(s)

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

        domain_signals = self._get_knowledge_signals().get("domain_signals", {})

        best_domain = "通用"
        best_score = 0
        for domain, keywords in domain_signals.items():
            pattern = "|".join(re.escape(k) for k in keywords)
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
        except Exception as e:
            log.debug("plan generation failed: %s", e)
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

