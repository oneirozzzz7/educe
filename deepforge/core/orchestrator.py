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
        self.domain_engine = None
        try:
            from deepforge.core.domain_engine import DomainEngine
            self.domain_engine = DomainEngine(knowledge=self.knowledge)
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

    async def run(self, user_input: str) -> WorkContext:
        self.context.user_request = user_input

        if self.context.artifacts.get("engineer_output"):
            return await self._run_modify(user_input)

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
        from deepforge.core.expert_router import get_expert_system_prompt

        has_files = bool(self.context.metadata.get("uploaded_files"))
        file_hint = ""
        if has_files:
            files = self.context.metadata["uploaded_files"]
            names = [f.name for f in files]
            file_hint = f"\n（用户上传了文件：{', '.join(names)}）"

        # 规则层短路——明确的文本任务
        if self._is_text_task(user_input):
            return await self._direct_reply(user_input, file_hint)

        # 模型判断是否需要编程
        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "请先配置模型。"}

        file_context = ""
        if has_files:
            from deepforge.core.file_handler import format_for_prompt
            file_context = format_for_prompt(self.context.metadata["uploaded_files"])

        try:
            judge = await client.chat(
                messages=[
                    {"role": "system", "content": (
                        "判断用户是否需要你编写代码/网页/工具/游戏/脚本。\n"
                        "- 需要编程 → 只回复：NEED_CODE\n"
                        "- 不需要 → 只回复：NO_CODE"
                    )},
                    {"role": "user", "content": user_input + file_hint},
                ],
                model=self.config.default_model.model,
                max_tokens=20,
                temperature=0.1,
            )
            if "NEED_CODE" in judge:
                return {"action": "code"}
        except Exception:
            pass

        # 非代码任务——用专家身份回复
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

    def _extract_expert_from_reply(self, reply: str) -> str:
        """从模型回复的开头提取它自认的专家身份"""
        import re
        first_line = reply.strip().split("\n")[0][:100]
        patterns = [
            r"作为.*?([一-鿿]+(?:专家|医[生师]|律师|教授|工程师|分析师|顾问|学者|科学家|厨师|编辑|教练|咨询师))",
            r"从([一-鿿]+)(?:角度|视角|层面)",
            r"以([一-鿿]+)的身份",
        ]
        for p in patterns:
            m = re.search(p, first_line)
            if m:
                return m.group(1) if "作为" not in p else m.group(1)
        if "医" in first_line: return "医学专家"
        if "法" in first_line: return "法律专家"
        if "数学" in first_line: return "数学专家"
        if "技术" in first_line or "编程" in first_line: return "技术专家"
        return "DeepForge"

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
        """规则层判断——明确的文本任务直接短路，不让弱模型误判"""
        import re
        text_patterns = [
            r"分析|总结|解释|翻译|评价|对比|比较|概括|梳理|归纳",
            r"是什么|怎么回事|为什么|什么意思|有什么区别",
            r"哪个.*最|多少|几个|排名|列出|介绍|推荐",
            r"帮我.*写|写一篇|写一段|写一首",
            r"你好|谢谢|再见|你是谁|你叫什么",
            r"怎么办|如何.*解决|建议|看法|观点",
        ]
        code_patterns = [
            r"做一个|创建一个|生成一个|开发一个|搭建",
            r"做个|写个|弄个|搞个",
            r"网页|网站|工具|游戏|扩展|脚本|程序|应用|APP|app",
            r"可视化|图表|看板|仪表盘|dashboard",
        ]
        text_score = sum(1 for p in text_patterns if re.search(p, user_input))
        code_score = sum(1 for p in code_patterns if re.search(p, user_input))
        return text_score > code_score and text_score >= 1

    async def _direct_reply(self, user_input: str, file_hint: str = "") -> dict:
        """用模型回复——通过prompt结构激发LLM深度思考"""
        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "请先配置模型。"}

        file_context = ""
        has_files = bool(self.context.metadata.get("uploaded_files"))
        if has_files:
            from deepforge.core.file_handler import format_for_prompt
            file_context = format_for_prompt(self.context.metadata["uploaded_files"])

        domain_context = self.context.metadata.get("domain_knowledge", "")

        system = (
            "你是一位博学且严谨的专家。回答问题时请遵循以下原则：\n"
            "1. 先判断这个问题属于什么专业领域，然后以该领域资深专家的身份回答\n"
            "2. 回答要有深度——不只是表面知识，要体现专业洞察\n"
            "3. 结构清晰——用标题、列表、分步骤组织长回答\n"
            "4. 诚实标注不确定的部分——'据我了解'或'这个需要进一步确认'\n"
            "5. 涉及医学、法律、金融等专业领域时，在末尾提醒用户咨询专业人士\n"
            "6. 用准确的术语但辅以通俗解释，让非专业人士也能理解\n"
            "\n在回答的开头，用一句话表明你以什么专家视角回答（如'作为一名医学工作者...'或'从计算机科学角度...'）。"
        )
        if domain_context:
            system += f"\n{domain_context}"

        try:
            result = await client.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_input + file_hint + file_context},
                ],
                model=self.config.default_model.model,
                max_tokens=self.config.default_model.max_tokens,
            )

            expert_name = self._extract_expert_from_reply(result)
            self.context.metadata["expert_name"] = expert_name
            console.print(f"[dim]🎓 {expert_name}[/dim]")

            return {"action": "reply", "content": result}
        except Exception as e:
            return {"action": "reply", "content": f"出错了: {e}"}
