from __future__ import annotations

import asyncio
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from deepforge.core.agent import BaseAgent
from deepforge.core.config import DeepForgeConfig
from deepforge.core.message import Message, MessageType, WorkContext, TaskStatus
from deepforge.core.observer import Observer
from deepforge.core.task_store import TaskStore

console = Console()

AGENT_COLORS = {
    "project_manager": "bold cyan",
    "product_manager": "bold green",
    "architect": "bold yellow",
    "engineer": "bold blue",
    "reviewer": "bold red",
    "crowd_user": "bold magenta",
    "memory_keeper": "bold white",
}

AGENT_ICONS = {
    "project_manager": "🎯",
    "product_manager": "📋",
    "architect": "🏗️",
    "engineer": "💻",
    "reviewer": "🔍",
    "crowd_user": "👥",
    "memory_keeper": "🧠",
}


class Orchestrator:
    def __init__(self, config: DeepForgeConfig, max_iterations: int = 3):
        self.config = config
        self.agents: dict[str, BaseAgent] = {}
        self.context = WorkContext()
        self._on_message: list[Callable[[Message], None]] = []
        self._on_chunk: list[Callable[[str, str], None]] = []
        self.max_iterations = max_iterations
        self.observer = Observer()
        self.task_store = TaskStore()

    def register(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent

    def on_message(self, callback: Callable[[Message], None]) -> None:
        self._on_message.append(callback)

    def on_chunk(self, callback: Callable[[str, str], None]) -> None:
        self._on_chunk.append(callback)

    def _notify(self, msg: Message) -> None:
        for cb in self._on_message:
            cb(msg)

    def _notify_chunk(self, agent_name: str, chunk: str) -> None:
        """流式chunk通知——逐字推送给前端"""
        for cb in self._on_chunk:
            cb(agent_name, chunk)

    def _display_message(self, msg: Message) -> None:
        icon = AGENT_ICONS.get(msg.sender, "🤖")
        color = AGENT_COLORS.get(msg.sender, "white")
        agent = self.agents.get(msg.sender)
        title = f"{icon} {agent.role if agent else msg.sender}"

        console.print()
        console.print(Panel(
            Markdown(msg.content),
            title=title,
            title_align="left",
            border_style=color,
            padding=(1, 2),
        ))

    async def run(self, user_input: str) -> WorkContext:
        self.context.user_request = user_input
        self.context.current_phase = "planning"

        initial_msg = Message(
            type=MessageType.USER_INPUT,
            sender="user",
            receiver="project_manager",
            content=user_input,
        )
        self.context.add_message(initial_msg)

        await self._process_message(initial_msg)
        return self.context

    async def _process_message(self, msg: Message, depth: int = 0) -> None:
        if depth > 30:
            console.print("[red]⚠ 达到最大递归深度，停止处理[/red]")
            return

        receiver = msg.receiver
        if receiver == "user":
            self._display_message(msg)
            return

        agent = self.agents.get(receiver)
        if agent is None:
            console.print(f"[red]⚠ 未找到Agent: {receiver}[/red]")
            return

        responses: list[Message] = []
        async for response in agent.handle(msg, self.context):
            self.context.add_message(response)
            self._notify(response)
            self._display_message(response)
            responses.append(response)

        for response in responses:
            if response.type == MessageType.HANDOFF:
                await self._process_message(response, depth + 1)

    def _needs_pipeline(self, user_input: str) -> bool:
        """判断是否需要编码pipeline"""
        text = user_input.strip().lower()
        if len(text) < 3:
            return False
        if self._is_content_task(user_input):
            return False

        code_signals = [
            "做一个", "帮我做", "创建一个", "开发一个", "写一个",
            "搭建", "实现", "build", "create", "make", "develop",
            "网页", "网站", "app", "工具", "游戏", "扩展", "插件",
            "html", "python", "脚本", "chrome",
        ]
        for s in code_signals:
            if s in text:
                return True
        return False

    def _is_content_task(self, user_input: str) -> bool:
        """判断是否是内容生成任务（攻略/报告/文案/翻译等）——不需要编码"""
        text = user_input.strip().lower()
        content_signals = [
            "攻略", "报告", "文案", "总结", "翻译", "分析",
            "计划", "方案", "建议", "对比", "评测", "介绍",
            "写一篇", "写一份", "帮我写", "列一个", "给我",
            "story", "article", "report", "summary", "plan",
        ]
        for s in content_signals:
            if s in text:
                return True
        return False

    async def _generate_content(self, user_input: str) -> str:
        """内容生成——直接调用模型，不走pipeline"""
        if not self.agents:
            return "暂时无法处理"
        client = next(iter(self.agents.values())).model_client
        if not client:
            return "暂时无法处理"
        try:
            return await client.chat(
                messages=[
                    {"role": "system", "content": "你是一个专业的内容创作助手。根据用户需求输出高质量、结构化的内容。使用Markdown格式，内容详实、有条理。"},
                    {"role": "user", "content": user_input},
                ],
                model=self.config.default_model.model,
                max_tokens=self.config.default_model.max_tokens,
            )
        except Exception as e:
            return f"生成失败: {e}"

    async def _quick_reply(self, user_input: str) -> str:
        """普通对话——直接调用模型，不带Agent角色prompt"""
        if not self.agents:
            return '你好！'
        client = next(iter(self.agents.values())).model_client
        if not client:
            return '你好！'
        try:
            return await client.chat(
                messages=[
                    {"role": "system", "content": "你是DeepForge，一个AI创作助手。简洁友好地回答用户问题。如果用户想创建什么东西，引导他描述具体需求。"},
                    {"role": "user", "content": user_input},
                ],
                model=self.config.default_model.model,
                max_tokens=500,
            )
        except Exception:
            return '你好！'

    async def run_pipeline(self, user_input: str) -> WorkContext:
        is_followup = bool(self.context.artifacts.get("engineer_output"))
        self.context.user_request = user_input
        self.context.metadata["on_chunk"] = lambda agent, chunk: self._notify_chunk(agent, chunk)

        if self._is_content_task(user_input):
            content = await self._generate_content(user_input)
            msg = Message(type=MessageType.RESULT, sender="assistant", receiver="user", content=content)
            self.context.add_message(msg)
            self._notify(msg)
            self._display_message(msg)
            return self.context

        if not self._needs_pipeline(user_input):
            reply = await self._quick_reply(user_input)
            msg = Message(type=MessageType.RESULT, sender="project_manager", receiver="user", content=reply)
            self.context.add_message(msg)
            self._notify(msg)
            self._display_message(msg)
            return self.context

        if is_followup:
            return await self._run_followup(user_input)

        import uuid
        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        pipeline = [
            "project_manager",
            "product_manager",
            "architect",
            "engineer",
            "reviewer",
            "crowd_user",
            "memory_keeper",
        ]

        current_content = user_input
        current_sender = "user"
        pipeline_success = True

        for agent_name in pipeline:
            if agent_name not in self.agents:
                continue
            if not self.config.agents.get(agent_name, None):
                continue

            self.context.current_phase = agent_name
            self.observer.start_agent(agent_name)

            msg = Message(
                type=MessageType.TASK if current_sender != "user" else MessageType.USER_INPUT,
                sender=current_sender,
                receiver=agent_name,
                content=current_content,
            )
            self.context.add_message(msg)

            try:
                async for response in self.agents[agent_name].handle(msg, self.context):
                    self.context.add_message(response)
                    self._notify(response)
                    self._display_message(response)
                    current_content = response.content
                    current_sender = agent_name
                self.observer.finish_agent(agent_name, success=True, summary=current_content[:80])
            except Exception as e:
                error_msg = f"[{agent_name}] 执行失败: {e}"
                console.print(f"[red]⚠ {error_msg}[/red]")
                self.observer.finish_agent(agent_name, success=False, error=str(e))
                err = Message(type=MessageType.ERROR, sender=agent_name, receiver="user", content=error_msg)
                self.context.add_message(err)
                self._notify(err)
                if agent_name in ("project_manager", "engineer"):
                    console.print("[red]关键Agent失败，停止流水线[/red]")
                    pipeline_success = False
                    break

        self.observer.finish_task(
            success=pipeline_success,
            project_type=self.context.artifacts.get("project_type", ""),
            file_count=len(self.context.artifacts.get("code_files", [])),
        )
        self.task_store.save_from_context(task_id, self.context)
        return self.context

    async def _run_followup(self, user_input: str) -> WorkContext:
        """多轮对话：基于上次产出进行修改"""
        console.print(f"\n[bold cyan]🔄 基于上次产出修改...[/bold cyan]\n")

        prev_output = self.context.artifacts.get("engineer_output", "")
        prev_files = self.context.artifacts.get("code_files", [])

        engineer = self.agents.get("engineer")
        if not engineer:
            return self.context

        self.context.current_phase = "engineer"
        modify_prompt = (
            f"用户要求修改：{user_input}\n\n"
            f"当前已有代码：\n{prev_output[:4000]}\n\n"
            f"请基于已有代码进行修改，输出修改后的完整文件。"
        )

        msg = Message(
            type=MessageType.TASK,
            sender="user",
            receiver="engineer",
            content=modify_prompt,
        )
        self.context.add_message(msg)

        try:
            async for response in engineer.handle(msg, self.context):
                self.context.add_message(response)
                self._notify(response)
                self._display_message(response)
        except Exception as e:
            console.print(f"[red]修改失败: {e}[/red]")

        return self.context

    async def run_iterative_pipeline(self, user_input: str) -> WorkContext:
        """带迭代循环的流水线"""
        self.context.user_request = user_input

        if self._is_content_task(user_input):
            content = await self._generate_content(user_input)
            msg = Message(type=MessageType.RESULT, sender="assistant", receiver="user", content=content)
            self.context.add_message(msg)
            self._notify(msg)
            self._display_message(msg)
            return self.context

        if not self._needs_pipeline(user_input):
            reply = await self._quick_reply(user_input)
            msg = Message(type=MessageType.RESULT, sender="project_manager", receiver="user", content=reply)
            self.context.add_message(msg)
            self._notify(msg)
            self._display_message(msg)
            return self.context

        self.context.metadata["iteration"] = 0

        pre_review = ["project_manager", "product_manager", "architect"]
        current_content = user_input
        current_sender = "user"

        for agent_name in pre_review:
            if agent_name not in self.agents:
                continue
            self.context.current_phase = agent_name
            msg = Message(
                type=MessageType.TASK if current_sender != "user" else MessageType.USER_INPUT,
                sender=current_sender,
                receiver=agent_name,
                content=current_content,
            )
            self.context.add_message(msg)

            async for response in self.agents[agent_name].handle(msg, self.context):
                self.context.add_message(response)
                self._notify(response)
                self._display_message(response)
                current_content = response.content
                current_sender = agent_name

        for iteration in range(1, self.max_iterations + 1):
            self.context.metadata["iteration"] = iteration
            console.print(f"\n[bold yellow]🔄 迭代轮次 {iteration}/{self.max_iterations}[/bold yellow]\n")

            self.context.current_phase = "engineer"
            eng_msg = Message(
                type=MessageType.TASK,
                sender=current_sender,
                receiver="engineer",
                content=current_content,
                data={"iteration": iteration},
            )
            self.context.add_message(eng_msg)

            eng_output = ""
            async for response in self.agents["engineer"].handle(eng_msg, self.context):
                self.context.add_message(response)
                self._notify(response)
                self._display_message(response)
                eng_output = response.content

            validation = self.context.artifacts.get("validation", {})
            if validation and not validation.get("passed", True):
                console.print(f"[yellow]⚠ 产出物验证未通过: {validation.get('summary', '')}[/yellow]")
                if iteration < self.max_iterations:
                    current_content = (
                        f"## 产出物验证失败\n\n"
                        f"问题: {'; '.join(validation.get('issues', []))}\n\n"
                        f"请修复以上问题，输出完整代码。"
                    )
                    current_sender = "reviewer"
                    continue

            self.context.current_phase = "reviewer"
            review_msg = Message(
                type=MessageType.TASK,
                sender="engineer",
                receiver="reviewer",
                content=f"## 工程师第{iteration}轮产出\n\n{eng_output}",
                data={"iteration": iteration},
            )
            self.context.add_message(review_msg)

            review_result = ""
            async for response in self.agents["reviewer"].handle(review_msg, self.context):
                self.context.add_message(response)
                self._notify(response)
                self._display_message(response)
                review_result = response.content

            passed = self._check_review_passed(review_result)

            if passed:
                console.print(f"\n[bold green]✅ 第{iteration}轮审查通过！[/bold green]\n")
                current_content = eng_output
                current_sender = "reviewer"
                break
            else:
                console.print(f"\n[bold red]🔴 第{iteration}轮审查未通过，回退修改[/bold red]\n")
                fix_instructions = self._extract_fix_instructions(review_result)
                current_content = (
                    f"## 审查反馈 - 第{iteration}轮\n\n"
                    f"### 需要修复的问题\n{fix_instructions}\n\n"
                    f"### 上一轮代码\n{eng_output}\n\n"
                    f"请根据审查反馈修复所有问题，输出完整修复后的代码。"
                )
                current_sender = "reviewer"

                if iteration == self.max_iterations:
                    console.print(f"\n[yellow]⚠ 达到最大迭代次数({self.max_iterations})[/yellow]\n")
                    current_content = eng_output

        has_deliverable = bool(self.context.artifacts.get("code_files"))

        if has_deliverable:
            post_review = ["crowd_user", "memory_keeper"]
            for agent_name in post_review:
                if agent_name not in self.agents:
                    continue
                self.context.current_phase = agent_name
                msg = Message(
                    type=MessageType.TASK,
                    sender=current_sender,
                    receiver=agent_name,
                    content=current_content,
                )
                self.context.add_message(msg)

                async for response in self.agents[agent_name].handle(msg, self.context):
                    self.context.add_message(response)
                    self._notify(response)
                    current_content = response.content
                    current_sender = agent_name

            await self._auto_preview()
        else:
            fail_msg = Message(
                type=MessageType.RESULT,
                sender="system",
                receiver="user",
                content="未能生成可用的产出物，请尝试更具体地描述需求。",
            )
            self.context.add_message(fail_msg)
            self._notify(fail_msg)
            self._display_message(fail_msg)

        return self.context

    async def _auto_preview(self) -> None:
        """任务完成后自动启动产出物预览"""
        output_dir = self.context.artifacts.get("output_dir")
        project_type = self.context.artifacts.get("project_type")
        if not output_dir or not project_type:
            return

        from pathlib import Path
        out = Path(output_dir)

        if project_type == "static_html":
            html_files = list(out.rglob("*.html"))
            if html_files:
                import subprocess
                port = 8899
                subprocess.Popen(
                    ["python", "-m", "http.server", str(port), "--directory", str(out)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                url = f"http://localhost:{port}/{html_files[0].relative_to(out)}"
                console.print(f"\n[bold green]🎉 产出物预览: {url}[/bold green]")
                import webbrowser
                webbrowser.open(url)
        elif project_type == "python_script":
            py_files = list(out.rglob("*.py"))
            if py_files:
                console.print(f"\n[bold green]🎉 运行: python {py_files[0]}[/bold green]")
        elif project_type == "chrome_extension":
            console.print(f"\n[bold green]🎉 Chrome扩展已生成: {out}[/bold green]")
            console.print("[dim]打开 chrome://extensions → 开发者模式 → 加载已解压扩展[/dim]")
        else:
            console.print(f"\n[bold green]🎉 产出物目录: {out}[/bold green]")

    def _check_review_passed(self, review_content: str) -> bool:
        """判断审查是否通过——默认不通过，必须有明确通过信号"""
        fail_signals = ["🔴", "必须修复", "严重问题", "阻塞性问题", "不通过", "❌"]
        for signal in fail_signals:
            if signal in review_content:
                return False

        import re
        score_match = re.search(r'(?:总体评分|评分|score)[：:\s]*(\d+)', review_content)
        if score_match:
            return int(score_match.group(1)) >= 7

        pass_signals = ["审查通过", "✅ 通过", "✅ 审查通过", "无阻塞性问题", "可以发布"]
        for signal in pass_signals:
            if signal in review_content:
                return True

        return False

    def _extract_fix_instructions(self, review_content: str) -> str:
        """从审查报告中提取修复指令"""
        lines = review_content.split("\n")
        fix_lines = []
        in_fix_section = False

        for line in lines:
            if any(kw in line for kw in ["🔴", "必须修复", "修复建议", "问题描述"]):
                in_fix_section = True
            if in_fix_section:
                fix_lines.append(line)
                if line.strip() == "" and len(fix_lines) > 3:
                    if any(kw in line for kw in ["🟡", "🟢", "总结", "评分"]):
                        break

        if fix_lines:
            return "\n".join(fix_lines)

        import re
        issues = re.findall(r'(?:🔴|❌|问题\d+)[^\n]*\n(?:[^\n]*\n){0,3}', review_content)
        if issues:
            return "\n".join(issues)

        return review_content[:1000]
