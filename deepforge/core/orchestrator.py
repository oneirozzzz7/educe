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
    def __init__(self, config: DeepForgeConfig):
        self.config = config
        self.agents: dict[str, BaseAgent] = {}
        self.context = WorkContext()
        self._on_message: list[Callable[[Message], None]] = []

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
        if depth > 20:
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
