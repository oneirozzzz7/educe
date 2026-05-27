from __future__ import annotations

import asyncio
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from deepforge.core.agent import BaseAgent
from deepforge.core.config import DeepForgeConfig
from deepforge.core.message import Message, MessageType, WorkContext, TaskStatus

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
        self.max_iterations = max_iterations

    def register(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent

    def on_message(self, callback: Callable[[Message], None]) -> None:
        self._on_message.append(callback)

    def _notify(self, msg: Message) -> None:
        for cb in self._on_message:
            cb(msg)

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

    async def run_pipeline(self, user_input: str) -> WorkContext:
        self.context.user_request = user_input
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

        for agent_name in pipeline:
            if agent_name not in self.agents:
                continue
            if not self.config.agents.get(agent_name, None):
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

        return self.context

    async def run_iterative_pipeline(self, user_input: str) -> WorkContext:
        """带迭代循环的流水线：审查不通过→回退工程师修改→再审查，最多max_iterations轮"""
        self.context.user_request = user_input
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
                    console.print(f"\n[yellow]⚠ 达到最大迭代次数({self.max_iterations})，继续后续流程[/yellow]\n")
                    current_content = eng_output

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
                self._display_message(response)
                current_content = response.content
                current_sender = agent_name

        return self.context

    def _check_review_passed(self, review_content: str) -> bool:
        """判断审查是否通过：基于评分和关键标记"""
        content_lower = review_content.lower()

        fail_signals = ["🔴 必须修复", "必须修复", "严重问题", "阻塞性问题", "不通过"]
        for signal in fail_signals:
            if signal in review_content:
                return False

        import re
        score_match = re.search(r'(?:总体评分|评分|score)[：:\s]*(\d+)', review_content)
        if score_match:
            score = int(score_match.group(1))
            return score >= 7

        pass_signals = ["审查通过", "✅ 通过", "无阻塞性问题", "整体良好", "可以发布"]
        for signal in pass_signals:
            if signal in review_content:
                return True

        return True

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
