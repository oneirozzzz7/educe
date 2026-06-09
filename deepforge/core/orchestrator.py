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
        self.unified_store = UnifiedKnowledgeStore(Path(".deepforge/unified"))

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

        # SelfEvolver: 计数 + 懒评估进化（每5次交互评估1次，降低延迟影响）
        if self.self_evolver:
            self.self_evolver.tick()
            if self.self_evolver.should_start_evolution():
                await self.self_evolver.generate_candidate()
                if self.self_evolver.evolving:
                    console.print("[dim]  self-evolver: candidate generated, starting lazy eval[/dim]")
            if self.self_evolver.evolving and self.self_evolver._call_count % 5 == 0:
                await self._evolve_one_step(user_input)
            if self.self_evolver.ab_complete():
                evo_result = self.self_evolver.finalize()
                if evo_result.get("result") == "evolved":
                    if self.activation_engine:
                        self.activation_engine._current_seed = self.self_evolver.current_best
                    console.print("[dim]  self-evolver: EVOLVED gen {}[/dim]".format(
                        evo_result.get("generation", "?")))
                else:
                    console.print("[dim]  self-evolver: kept current[/dim]")

        # 检测用户对上一轮回答的反馈信号
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

            # 回填上一轮构建的 user_signal 到统一知识系统
            if self.unified_store and signal != "neutral":
                self.unified_store.record_signal({
                    "type": "user_feedback",
                    "session_id": self.context.metadata.get("session_id", ""),
                    "signal": signal,
                    "weight": weight,
                })

            # 负向信号→降级上一轮用过的知识 + 标记下一轮不提取
            if signal == "error":
                self.context.metadata["_skip_next_extraction"] = True
                recalled_ids = self.context.metadata.get("_recalled_knowledge_ids", [])
                for eid in recalled_ids:
                    if self.unified_store:
                        self.unified_store.record_usage(eid, success=False)
            else:
                self.context.metadata.pop("_skip_next_extraction", None)

        self.conversation.add_user(user_input, file_content)
        if hasattr(self, 'state'):
            self.state.add_turn("user", user_input)

        if file_content:
            self.context.metadata["uploaded_files_text"] = file_content
        else:
            active_file = self.conversation.get_active_file_context(user_input)
            if active_file:
                self.context.metadata["uploaded_files_text"] = active_file
            else:
                self.context.metadata.pop("uploaded_files_text", None)

        # 每轮独立判断意图——不依赖上一轮状态
        skill_prompt = self._match_skill(user_input)
        if skill_prompt:
            self.context.metadata["skill_prompt"] = skill_prompt

        if self.domain_engine:
            domain = self.domain_engine.match_domain(user_input)
            domain_knowledge = self.domain_engine.inject_knowledge(user_input, domain)
            if domain_knowledge:
                self.context.metadata["domain_knowledge"] = domain_knowledge

        # 统一知识系统：recall 让模型判断相关性
        if not self.context.metadata.get("domain_knowledge"):
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
                    self.context.metadata["domain_knowledge"] = (
                        "\n## 相关知识\n" + "\n".join(
                            f"- {e.content.body}" for e in recalled))
                    self.context.metadata["_recalled_knowledge_ids"] = [
                        e.id for e in recalled]

        # 构建认知黑板——从各模块收集信息
        from deepforge.core.cognitive_state import CognitiveState
        cs = CognitiveState()

        # 意图层（ContextAnalyzer）
        if self.context_analyzer:
            signals = self.context_analyzer.analyze(
                user_input, self.conversation.turns, self.context.artifacts)
            self.context.metadata["_context_signals"] = signals
            cs.intent_clarity = signals.user_intent_hint if signals.user_intent_hint != "unclear" else "clear"
            if signals.topic_continuity == "switch":
                cs.phase = "opening"

        # 能力层（QualityTracker + domain）
        detected_domain = self._detect_domain(user_input, "")
        cs.domain = detected_domain
        stats = self.quality_tracker.get_domain_stats()
        domain_stat = stats.get(detected_domain, {})
        if domain_stat.get("total_responses", 0) >= 5:
            cs.task_success_rate = domain_stat.get("avg_quality", 0.8)

        # 用户层（UserProfile）
        session_id = self.context.metadata.get("session_id", "")
        if self.profile_manager and session_id:
            profile = self.profile_manager.get_or_create(session_id)
            cs.user_expertise = profile.expertise_level
            cs.user_preference = profile.response_preference

        # 对话层
        cs.turn_count = len(self.conversation.turns)
        cs.last_relevance = self.context.metadata.get("_validation_result", {}).get("relevant", True)
        if cs.last_relevance is True:
            cs.last_relevance = 1.0
        elif cs.last_relevance is False:
            cs.last_relevance = 0.3

        # 能力层补充（ActivationEvolver→best_seed）
        if self.activation_engine and hasattr(self.activation_engine, '_evolver') and self.activation_engine._evolver:
            cs.best_seed = self.activation_engine._evolver.get_best_seed(detected_domain)
        if self.self_evolver:
            cs.best_seed = self.self_evolver.current_best

        # 对话阶段推断（不硬编码——从状态推断）
        has_prev_code = bool(self.context.artifacts.get("engineer_output"))
        if cs.turn_count == 0:
            cs.phase = "opening"
        elif has_prev_code and cs.turn_count >= 2:
            cs.phase = "reviewing"
        elif cs.turn_count >= 6:
            cs.phase = "deep"
        else:
            cs.phase = "conversing"

        # 信心层（CredibilityEngine）
        if self.credibility:
            cred_result = self.credibility.assess(
                user_input, "", detected_domain,
                user_signal=self.context.metadata.get("_last_user_signal", "neutral"))
            cs.framework_confidence = cred_result.get("level", "medium")

        self.cognitive_state = cs
        self.context.metadata["_cognitive_state"] = cs.to_dict()

        # 如果有用户决策回来——直接走构建
        if self.context.metadata.get("_user_decisions"):
            self.context.metadata["expert_name"] = "编程专家"
            self.cognitive_state.phase = "building"
            # Restore transcript from pending state
            transcript = self.context.metadata.get("_transcript")
            if transcript:
                decisions = self.context.metadata["_user_decisions"]
                choices = ", ".join(d.get("choice", "") for d in decisions)
                transcript.add("plan", "user", "确认选择: {}".format(choices[:100]))
            result = await self._run_build(user_input)
            self.context.metadata.pop("_user_decisions", None)
            self.context.metadata.pop("_skip_analysis", None)
            self.context.metadata.pop("_pending_request", None)
            return result

        # Reuse existing transcript (cross-turn continuity) or create new one
        from deepforge.core.transcript import TaskTranscript
        transcript = self.context.metadata.get("_transcript")
        if transcript:
            transcript.user_request = user_input
        else:
            transcript = TaskTranscript(user_input)

        # Wire transcript to WebSocket via _notify + persist to state
        def push_transcript_event(evt: dict):
            import json as _json
            evt_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                content="__TOOL_EVENT__" + _json.dumps(evt, ensure_ascii=False))
            self._notify(evt_msg)
            # Persist to SessionState
            if hasattr(self, 'state'):
                self.state.transcript.append(evt)
        transcript.on_update = push_transcript_event
        self.context.metadata["_transcript"] = transcript
        if hasattr(self, 'state'):
            self.context.metadata["_session_state"] = self.state

        import time as _time
        _t0 = _time.time()
        decision = await self._decide(user_input)
        _decide_elapsed = round(_time.time() - _t0, 1)

        # _decide 可能直接返回 WorkContext（reply/memorize已处理完毕）
        if not isinstance(decision, dict):
            return self.context

        if decision["action"] == "clarify":
            transcript.add("analyze", "system",
                "意图模糊，追问确认", elapsed=_decide_elapsed)
            clarify_msg = Message(
                type=MessageType.RESULT, sender="assistant", receiver="user",
                content=decision.get("question", ""))
            self._notify(clarify_msg)
            self._display(clarify_msg)
            self.cognitive_state.phase = "exploring"
            session_id = self.context.metadata.get("session_id", "")
            if session_id:
                self.session_store.append_turn(
                    session_id, user_input, decision.get("question", ""),
                    turn_type="clarify", domain=self.cognitive_state.domain)
            return self.context

        if decision["action"] in ("code", "build_direct"):
            self.context.metadata["expert_name"] = "编程专家"
            transcript.add("analyze", "system", "任务类型: BUILD", elapsed=_decide_elapsed)

            # 复杂任务 + 首次构建 → 先提议方案让用户选
            has_prev_code = bool(self.context.artifacts.get("code_files"))
            if not has_prev_code:
                _t1 = _time.time()
                complexity = await self._assess_complexity(user_input)
                self.context.metadata["_task_complexity"] = complexity
                transcript.add("analyze", "system", "复杂度: {}".format(complexity.upper()), elapsed=round(_time.time() - _t1, 1))

                if complexity == "complex":
                    transcript.current_phase = "plan"
                    _t2 = _time.time()
                    plans = await self._generate_plans(user_input)
                    if plans and len(plans) >= 2:
                        transcript.add("plan", "model", "生成了{}个方案".format(len(plans)), elapsed=round(_time.time() - _t2, 1))
                        plan_msg = Message(
                            type=MessageType.SYSTEM, sender="planner", receiver="user",
                            content="__PLAN_PROPOSAL__",
                            data={"plans": plans, "original_request": user_input})
                        self._notify(plan_msg)
                        self.context.metadata["_pending_plans"] = plans
                        self.context.metadata["_pending_request"] = user_input
                        self.cognitive_state.phase = "planning"
                        return self.context

            self.cognitive_state.phase = "building"
            transcript.current_phase = "build"
            return await self._run_build(user_input)
        else:
            content = decision["content"]
            if self.config.hallucination_guard.enabled:
                content = await self._audit(user_input, content)
            msg = Message(type=MessageType.RESULT, sender="assistant", receiver="user", content=content)
            self.context.add_message(msg)
            self._notify(msg)
            self._display(msg)
            self._feedback_success()

            # Session级保存（替代per-turn碎片化存储）
            session_id = self.context.metadata.get("session_id", "")
            if session_id:
                self.session_store.append_turn(
                    session_id, user_input, content,
                    turn_type="text",
                    domain=self.context.metadata.get("expert_name", ""),
                )

            return self.context

    # ═══════════════════════════════════════
    #  Builder → Tester → 循环（优化版）
    # ═══════════════════════════════════════

    async def _run_build(self, user_input: str) -> WorkContext:
        pipeline_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user", content="__PIPELINE_START__")
        self._notify(pipeline_msg)

        # 注入统一知识系统到 context，供 builder 使用
        if self.unified_store:
            self.context.metadata["_unified_store"] = self.unified_store

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

        # 采集 SessionSignal 到统一知识系统
        if self.unified_store:
            import time as _t
            transcript = self.context.metadata.get("_transcript")
            phases = {}
            if transcript:
                for e in transcript.entries:
                    if e.elapsed and e.phase:
                        phases[e.phase] = phases.get(e.phase, 0) + e.elapsed

            # 对 recall 过的知识记录使用结果
            recalled_ids = self.context.metadata.get("_recalled_knowledge_ids", [])
            for kid in recalled_ids:
                self.unified_store.record_usage(kid, success=has_output)

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
            turn_type = "code" if has_output else "text"
            self.state.add_turn("assistant", summary, turn_type)
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
            "2. 期望的产出形态？（代码文件/文字分析/需要追问确认？记住偏好？）\n"
            "3. 如果有已有产物，是想改进还是在讨论别的？\n\n"
            "输出格式（严格）：\n"
            "ACTION: build | reply | clarify | memorize\n"
            "INTENT: 一句话描述用户真实意图\n"
            "- build: 需要产出可运行的文件（网页/工具/游戏/脚本/演示/可视化等）\n"
            "- reply: 纯文字对话（提问/分析/翻译/闲聊）\n"
            "- clarify: 意图模糊需要追问（如'继续优化'但不知道优化什么方向）\n"
            "- memorize: 用户要求记住偏好/规则/模式（'记住...'、'以后每次...'、'下次...'）\n"
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

    async def _handle_memorize(self, user_input: str) -> dict:
        """用户要求记住偏好/规则——模型结构化解析后写入统一知识系统"""
        client = self._get_client()
        if not client or not self.unified_store:
            return {"action": "reply", "content": "知识系统未初始化，无法记忆。"}

        try:
            result = await client.chat(
                messages=[
                    {"role": "system", "content": (
                        "用户要求你记住一条偏好或规则。解析用户的指令，提取结构化信息。\n"
                        "输出JSON格式（严格）：\n"
                        '{"content": "知识内容（简洁一句话）", '
                        '"category": "preference|rule|pattern", '
                        '"domain": "tech|design|general", '
                        '"trigger": "在什么场景下应用这条知识"}\n'
                        "只输出JSON，不要其他文字。"
                    )},
                    {"role": "user", "content": user_input},
                ],
                model=self.config.default_model.model,
                max_tokens=200, temperature=0.0,
            )
            import json as _json
            parsed = _json.loads(result.strip().strip("```json").strip("```"))
            content = parsed.get("content", user_input)
            category = parsed.get("category", "insight")
            domain = parsed.get("domain", "general")
            trigger = parsed.get("trigger", "")

            conditions = []
            if trigger:
                conditions.append({"type": "context", "value": trigger})

            entry_id = self.unified_store.add(
                content=content,
                source="user",
                maturity="pattern",
                scope="project",
                category=category,
                domain=domain,
                conditions=conditions,
                session_id=self.context.metadata.get("session_id", ""),
            )
            log.info("_handle_memorize | stored id=%s content=%s", entry_id, content[:60])

            reply = f"已记住：{content}"
            msg = Message(type=MessageType.RESULT, sender="assistant",
                         receiver="user", content=reply)
            self.context.add_message(msg)
            self._notify(msg)
            return self.context
        except Exception as e:
            log.error("_handle_memorize | error: %s", str(e)[:100])
            reply = f"记忆失败：{str(e)[:50]}"
            msg = Message(type=MessageType.RESULT, sender="assistant",
                         receiver="user", content=reply)
            self.context.add_message(msg)
            self._notify(msg)
            return self.context

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
        l1 = self.knowledge.get_l1_compiled() if self.knowledge else []

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
                self.state.add_turn("assistant", raw)

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
