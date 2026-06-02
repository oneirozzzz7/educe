"""
DeepForge Orchestrator v2
3-Agent架构：Builder + Tester + Planner
Orchestrator做路由和循环控制，不是Agent
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Callable

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

            # 负向信号→降级上一轮用过的知识 + 标记下一轮不提取
            if signal == "error":
                self.context.metadata["_skip_next_extraction"] = True
                recalled_ids = getattr(self.knowledge, '_last_recalled_ids', [])
                for eid in recalled_ids:
                    self.knowledge.record_failure(eid)
            else:
                self.context.metadata.pop("_skip_next_extraction", None)

        self.conversation.add_user(user_input, file_content)

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
            result = await self._run_build(user_input)
            self.context.metadata.pop("_user_decisions", None)
            self.context.metadata.pop("_skip_analysis", None)
            self.context.metadata.pop("_pending_request", None)
            return result

        decision = await self._decide(user_input)

        if decision["action"] == "clarify":
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

        if decision["action"] == "propose_plans":
            self.context.metadata["expert_name"] = "编程专家"
            plans = await self._generate_plans(user_input)
            if plans:
                plan_msg = Message(
                    type=MessageType.SYSTEM, sender="planner", receiver="user",
                    content="__PLAN_PROPOSAL__",
                    data={"plans": plans, "original_request": user_input})
                self._notify(plan_msg)
                self.context.metadata["_pending_plans"] = plans
                self.context.metadata["_pending_request"] = user_input
                self.cognitive_state.phase = "planning"
                return self.context

        if decision["action"] in ("code", "build_direct"):
            self.context.metadata["expert_name"] = "编程专家"
            self.cognitive_state.phase = "building"
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

        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        # ═══ A. 生成需求清单（核心功能 checklist）═══
        checklist = []
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
        if checklist:
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

        # ═══ C. Checklist 验收 ═══
        has_output = bool(self.context.artifacts.get("code_files"))
        if has_output and checklist:
            try:
                from deepforge.core.checklist_judge import verify_checklist
                code_output = self.context.artifacts.get("engineer_output", "")
                if len(code_output) < 100:
                    # Read actual files for verification
                    from pathlib import Path
                    output_dir = self.context.artifacts.get("output_dir", "")
                    code_files = self.context.artifacts.get("code_files", [])
                    parts = []
                    for fp in code_files[:3]:
                        p = Path(fp) if Path(fp).is_absolute() else Path(output_dir) / fp
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

        # Session级保存
        session_id = self.context.metadata.get("session_id", "")
        if session_id:
            code_output = self.context.artifacts.get("engineer_output", "")[:5000]
            # If engineer_output is just a marker (agentic mode), read actual file content
            if len(code_output) < 100 and self.context.artifacts.get("code_files"):
                try:
                    from pathlib import Path
                    output_dir = self.context.artifacts.get("output_dir", "")
                    code_files = self.context.artifacts.get("code_files", [])
                    file_contents = []
                    for fp in code_files[:3]:
                        p = Path(fp) if Path(fp).is_absolute() else Path(output_dir) / fp
                        if p.exists():
                            content = p.read_text(encoding="utf-8", errors="ignore")[:10000]
                            file_contents.append(f"```filepath:{p.name}\n{content}\n```")
                    if file_contents:
                        code_output = "\n\n".join(file_contents)
                except Exception:
                    pass
            self.session_store.append_turn(
                session_id, user_input, code_output,
                turn_type="code",
                domain="tech",
            )

        # 给conversation加完成记录（简短摘要，不是完整代码）
        code_files = self.context.artifacts.get("code_files", [])
        if code_files:
            filenames = [f.split("/")[-1] for f in code_files]
            summary = "[已完成代码生成] 文件：{}".format(", ".join(filenames))
        else:
            summary = "[代码任务未能完成]"
        self.conversation.add_assistant(summary, domain="tech")

        if has_output and self.config.evolution.enabled:
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

        # 可靠的2选1路由（已验证100%准确）+ CognitiveState信号增强
        router_system = (
            "判断用户需要文字回答还是编写代码。\n"
            "REPLY：聊天/提问/分析/翻译/写文章等\n"
            "BUILD：做网页/工具/游戏/脚本/程序等\n"
            "只回复REPLY或BUILD。"
        )

        has_prev_code = bool(self.context.artifacts.get("engineer_output"))
        if has_prev_code:
            router_system += "\n注意：之前生成过代码。修改/调整/优化等=BUILD。"

        context_signals = self._build_confidence_context(user_input, cs)
        user_msg = user_input + file_hint
        if context_signals:
            user_msg += "\n\n[上下文]\n" + context_signals

        try:
            result = await client.chat(
                messages=[
                    {"role": "system", "content": router_system},
                    {"role": "user", "content": user_msg},
                ],
                model=self.config.default_model.model,
                max_tokens=10, temperature=0.0,
            )
            action = "code" if "BUILD" in result.upper() else "reply"
        except Exception:
            action = "reply"

        self.context.metadata["_route_decision"] = {
            "action": action,
            "cognitive_state": cs.to_dict() if cs else {},
        }

        if action == "reply":
            return await self._direct_reply(user_input, file_hint)
        return {"action": action}

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
                        "从简单到复杂排列。不要其他内容。")},
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
        self.context.user_request = build_input
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
