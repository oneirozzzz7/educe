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

        from deepforge.core.conversation import ConversationManager
        self.conversation = ConversationManager()

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

        decision = await self._decide(user_input)

        if decision["action"] == "code":
            self.context.metadata["expert_name"] = "编程专家"
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

            # 保存到历史（文本回复也保存，不只是代码任务）
            import uuid as _uuid
            task_id = _uuid.uuid4().hex[:8]
            self.task_store.save_from_context(task_id, self.context, response=content)

            return self.context

    # ═══════════════════════════════════════
    #  Builder → Tester → 循环（优化版）
    # ═══════════════════════════════════════

    async def _run_build(self, user_input: str) -> WorkContext:
        pipeline_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user", content="__PIPELINE_START__")
        self._notify(pipeline_msg)

        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        max_tester_rejects = 1  # 优化4: Tester打回上限1次

        for iteration in range(1, self.max_iterations + 1):
            if iteration == 1:
                build_input = user_input
            else:
                test_report = self.context.artifacts.get("test_result", {}).get("report", "")
                build_input = f"测试未通过，请修复：\n{test_report[:1000]}\n\n原始需求：{user_input}"

            await self._run_agent("builder", build_input, "user", timeout=150)

            if not self.context.artifacts.get("code_files"):
                continue

            # 优化2: Tester轻量化——先用工具快速检查
            if "tester" in self.agents:
                quick_pass = await self._quick_tool_check()
                if quick_pass and iteration <= max_tester_rejects:
                    # 工具检查通过——跳过LLM Tester（省时间）
                    console.print(f"[green]✅ 工具验证通过 (迭代{iteration})[/green]")
                    break
                elif not quick_pass and iteration <= max_tester_rejects:
                    # 工具检查有问题——才调LLM Tester深度分析
                    await self._run_agent("tester", "请测试Builder的产出物", "builder", timeout=60)
                    test_result = self.context.artifacts.get("test_result", {})
                    if test_result.get("passed", True):
                        console.print(f"[green]✅ 测试通过 (迭代{iteration})[/green]")
                        break
                    else:
                        console.print(f"[yellow]🔄 测试未通过，回退修复 (迭代{iteration})[/yellow]")
                else:
                    # 优化4: 超过打回上限——带着反馈直接交付
                    console.print(f"[yellow]⚠ 达到打回上限，交付当前版本[/yellow]")
                    break
            else:
                break

        has_output = bool(self.context.artifacts.get("code_files"))
        self.observer.finish_task(success=has_output, project_type=self.context.artifacts.get("project_type", ""),
                                 file_count=len(self.context.artifacts.get("code_files", [])))
        self.task_store.save_from_context(task_id, self.context)

        if has_output and self.config.evolution.enabled:
            asyncio.create_task(self._evolve_from_result())

        if not has_output:
            fail_msg = Message(type=MessageType.RESULT, sender="system", receiver="user",
                              content="未能生成可用的产出物，请更具体描述需求。")
            self.context.add_message(fail_msg)
            self._notify(fail_msg)

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

        has_files = bool(self.context.metadata.get("uploaded_files"))
        file_hint = ""
        if has_files:
            files = self.context.metadata["uploaded_files"]
            names = [f.name for f in files]
            file_hint = "\n（用户上传了文件：{}）".format(", ".join(names))

        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "请先配置模型。"}

        file_context = ""
        if has_files:
            from deepforge.core.file_handler import format_for_prompt
            file_context = format_for_prompt(self.context.metadata["uploaded_files"])

        # ContextAnalyzer：生成上下文信号
        ctx_signals = None
        if self.context_analyzer:
            ctx_signals = self.context_analyzer.analyze(
                user_input, self.conversation.turns, self.context.artifacts
            )
            self.context.metadata["_context_signals"] = ctx_signals

            # 快速路径：如果ContextAnalyzer明确判断是代码修改
            if ctx_signals.user_intent_hint == "modify_code":
                return {"action": "code"}

        judge_system = (
            "你是意图分类器。判断用户是否需要编写代码/网页/工具/游戏/脚本。\n"
            "NEED_CODE的例子：做一个计算器、做个番茄钟、写个网页、帮我做一个XX、生成代码\n"
            "NO_CODE的例子：什么是XX、XX是什么、怎么理解XX、帮我分析、翻译、写文章\n"
            "只回复NEED_CODE或NO_CODE，不要回复其他内容。"
        )

        has_prev_code = bool(self.context.artifacts.get("engineer_output"))
        if has_prev_code:
            judge_system += "\n注意：之前生成过代码。修改/调整/优化/加功能/改颜色/改大小等=NEED_CODE。"

        # 注入上下文信号（帮助弱模型做判断）
        if ctx_signals and ctx_signals.signals:
            context_hint = self.context_analyzer.build_context_hint(ctx_signals)
            if context_hint:
                judge_system += context_hint

        messages = [{"role": "system", "content": judge_system}]
        messages.append({"role": "user", "content": user_input + file_hint})

        try:
            judge = await client.chat(
                messages=messages,
                model=self.config.default_model.model,
                max_tokens=20,
                temperature=0.1,
            )
            if "NEED_CODE" in judge:
                return {"action": "code"}
        except Exception:
            pass

        return await self._direct_reply(user_input, file_hint)

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

        if self.activation_engine:
            system = self.activation_engine.build_activation_prompt(
                user_input=user_input,
                domain_context=domain_context + ctx_hint,
                l1_compiled=all_knowledge[:8] if all_knowledge else None,
            )
        else:
            system = "你是一位专业的AI助手，请准确回答用户的问题。"

        history = self.conversation.get_history_for_llm()
        user_content = user_input + (f"\n{file_hint}" if file_hint else "") + (f"\n{file_context}" if file_context else "")

        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})

        try:
            raw = await client.chat(
                messages=messages,
                model=self.config.default_model.model,
                max_tokens=self.config.default_model.max_tokens,
            )

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
                self.quality_tracker.record(
                    question=user_input, domain=domain_tag,
                    seed=self.activation_engine._current_seed[:60],
                    response=raw, user_signal=user_signal,
                    signal_weight=signal_weight,
                    model=self.config.default_model.model,
                )

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
            else:
                self.context.metadata["expert_name"] = "DeepForge"

            self.context.artifacts["last_text_domain"] = domain_tag
            self.conversation.add_assistant(raw, domain=domain_tag)

            return {"action": "reply", "content": raw}
        except Exception as e:
            return {"action": "reply", "content": f"出错了: {e}"}
