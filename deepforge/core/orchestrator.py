from __future__ import annotations

import asyncio
import json
import re
import uuid
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

AGENT_ICONS = {
    "project_manager": "🎯", "product_manager": "📋", "architect": "🏗️",
    "engineer": "💻", "reviewer": "🔍", "crowd_user": "👥", "memory_keeper": "🧠",
}

HIDDEN_FROM_USER = {"memory_keeper", "crowd_user"}

PIPELINE = ["project_manager", "product_manager", "architect", "engineer", "reviewer", "crowd_user", "memory_keeper"]


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
        for cb in self._on_chunk:
            cb(agent_name, chunk)

    def _display(self, msg: Message) -> None:
        if msg.sender in HIDDEN_FROM_USER:
            return
        icon = AGENT_ICONS.get(msg.sender, "🤖")
        console.print(Panel(Markdown(msg.content[:500]), title=f"{icon} {msg.sender}", border_style="cyan", padding=(0, 1)))

    # ═══════════════════════════════════════════
    # 唯一入口 — 不分类意图，模型自己决定
    # ═══════════════════════════════════════════

    async def run(self, user_input: str) -> WorkContext:
        """Claude Code风格：所有请求走同一入口，模型自己决定怎么做"""
        self.context.user_request = user_input

        if self.context.artifacts.get("engineer_output"):
            return await self._run_followup(user_input)

        decision = await self._smart_decide(user_input)

        if decision["action"] == "code_complex":
            return await self._run_code_pipeline(user_input)
        elif decision["action"] == "code_simple":
            return await self._run_quick_code(user_input)
        else:
            msg = Message(type=MessageType.RESULT, sender="assistant", receiver="user", content=decision["content"])
            self.context.add_message(msg)
            self._notify(msg)
            self._display(msg)
            return self.context

    async def _run_quick_code(self, user_input: str) -> WorkContext:
        """简单编码任务：直接让工程师写，跳过PM/PD/Arch"""
        pipeline_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                              content="__PIPELINE_START__")
        self._notify(pipeline_msg)

        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        output, _ = await self._run_agent("engineer", user_input, "user")

        validation = self.context.artifacts.get("validation", {})
        if validation and not validation.get("passed", True):
            output, _ = await self._run_agent("engineer",
                f"上次代码有问题({validation.get('summary','')})\n原始需求：{user_input}\n请重新输出完整代码。",
                "reviewer", data={"iteration": 2})

        has_output = bool(self.context.artifacts.get("code_files"))
        self.observer.finish_task(
            success=has_output,
            project_type=self.context.artifacts.get("project_type", ""),
            file_count=len(self.context.artifacts.get("code_files", [])),
        )
        self.task_store.save_from_context(task_id, self.context)

        if not has_output:
            fail_msg = Message(type=MessageType.RESULT, sender="system", receiver="user",
                              content="未能生成产出物，请更具体描述需求。")
            self.context.add_message(fail_msg)
            self._notify(fail_msg)

        return self.context

    async def _smart_decide(self, user_input: str) -> dict:
        """一次模型调用：判断任务类型和复杂度"""
        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "暂时无法处理，请检查模型配置。"}

        try:
            result = await client.chat(
                messages=[
                    {"role": "system", "content": (
                        "你是DeepForge助手。判断用户需求并执行：\n"
                        "- 需要编程做复杂产品(多页面/复杂交互/需设计)→只回复：NEED_CODE_COMPLEX\n"
                        "- 需要编程做简单工具(单文件/小脚本/简单网页)→只回复：NEED_CODE_SIMPLE\n"
                        "- 其他(聊天/写文章/攻略/翻译/分析等)→直接输出完整内容\n\n"
                        "注意：番茄钟、计算器、格式化工具、密码生成器、倒计时等都是SIMPLE。"
                    )},
                    {"role": "user", "content": user_input},
                ],
                model=self.config.default_model.model,
                max_tokens=self.config.default_model.max_tokens,
            )

            text = result.strip()
            if text.startswith("NEED_CODE_COMPLEX"):
                return {"action": "code_complex"}
            elif text.startswith("NEED_CODE_SIMPLE"):
                return {"action": "code_simple"}
            else:
                return {"action": "reply", "content": result}

        except Exception as e:
            return {"action": "reply", "content": f"出错了: {e}"}

    # ═══════════════════════════════════════════
    # 编码 Pipeline（带迭代）
    # ═══════════════════════════════════════════

    async def _run_code_pipeline(self, user_input: str) -> WorkContext:
        """完整的编码pipeline"""
        pipeline_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                              content="__PIPELINE_START__")
        self._notify(pipeline_msg)
        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        pre_review = ["project_manager", "product_manager", "architect"]
        current_content = user_input
        current_sender = "user"

        for agent_name in pre_review:
            current_content, current_sender = await self._run_agent(
                agent_name, current_content, current_sender
            )

        for iteration in range(1, self.max_iterations + 1):
            console.print(f"\n[bold yellow]🔄 迭代 {iteration}/{self.max_iterations}[/bold yellow]")

            current_content, current_sender = await self._run_agent(
                "engineer", current_content, current_sender, data={"iteration": iteration}
            )

            validation = self.context.artifacts.get("validation", {})
            if validation and not validation.get("passed", True) and iteration < self.max_iterations:
                current_content = f"验证失败: {validation.get('summary','')}\n请修复并输出完整代码。"
                current_sender = "reviewer"
                continue

            review_content, _ = await self._run_agent(
                "reviewer", f"工程师第{iteration}轮产出:\n{current_content}", "engineer",
                data={"iteration": iteration}
            )

            if self._review_passed(review_content):
                console.print(f"\n[green]✅ 审查通过[/green]")
                break
            elif iteration < self.max_iterations:
                console.print(f"\n[red]🔴 审查未通过，回退修改[/red]")
                fix = self._extract_fixes(review_content)
                current_content = f"审查反馈:\n{fix}\n\n上一轮代码:\n{current_content}\n\n请修复后输出完整代码。"
                current_sender = "reviewer"

        has_output = bool(self.context.artifacts.get("code_files"))

        if has_output:
            for agent_name in ["crowd_user", "memory_keeper"]:
                await self._run_agent(agent_name, current_content, current_sender)

        self.observer.finish_task(
            success=has_output,
            project_type=self.context.artifacts.get("project_type", ""),
            file_count=len(self.context.artifacts.get("code_files", [])),
        )
        self.task_store.save_from_context(task_id, self.context)

        if not has_output:
            fail_msg = Message(type=MessageType.RESULT, sender="system", receiver="user",
                              content="未能生成可用的产出物，请尝试更具体地描述需求。")
            self.context.add_message(fail_msg)
            self._notify(fail_msg)

        return self.context

    # ═══════════════════════════════════════════
    # 修改已有产出物
    # ═══════════════════════════════════════════

    async def _run_followup(self, user_input: str) -> WorkContext:
        """基于上次产出物修改"""
        prev_output = self.context.artifacts.get("engineer_output", "")
        modify_prompt = f"用户要求修改：{user_input}\n\n当前代码：\n{prev_output[:4000]}\n\n输出修改后的完整文件。"
        await self._run_agent("engineer", modify_prompt, "user")
        return self.context

    # ═══════════════════════════════════════════
    # 通用Agent执行
    # ═══════════════════════════════════════════

    async def _run_agent(self, agent_name: str, content: str, sender: str, data: dict | None = None) -> tuple[str, str]:
        """执行单个Agent，返回(output_content, agent_name)"""
        agent = self.agents.get(agent_name)
        if not agent:
            return content, sender

        self.context.current_phase = agent_name
        self.observer.start_agent(agent_name)

        msg = Message(
            type=MessageType.TASK if sender != "user" else MessageType.USER_INPUT,
            sender=sender, receiver=agent_name, content=content,
            data=data or {},
        )
        self.context.add_message(msg)

        output = content
        try:
            async for response in agent.handle(msg, self.context):
                self.context.add_message(response)
                if response.sender not in HIDDEN_FROM_USER:
                    self._notify(response)
                self._display(response)
                output = response.content
            self.observer.finish_agent(agent_name, success=True, summary=output[:80])
        except Exception as e:
            console.print(f"[red]⚠ [{agent_name}] 失败: {e}[/red]")
            self.observer.finish_agent(agent_name, success=False, error=str(e))
            if agent_name in ("project_manager", "engineer"):
                raise

        return output, agent_name

    # ═══════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════

    def _get_client(self):
        if not self.agents:
            return None
        agent = next(iter(self.agents.values()))
        return agent.model_client

    def _review_passed(self, review: str) -> bool:
        for signal in ["🔴", "❌", "必须修复", "不通过", "严重问题"]:
            if signal in review:
                return False
        m = re.search(r'(?:评分|score)[：:\s]*(\d+)', review)
        if m:
            return int(m.group(1)) >= 7
        for signal in ["✅ 通过", "✅ 审查通过", "审查通过"]:
            if signal in review:
                return True
        return False

    def _extract_fixes(self, review: str) -> str:
        lines = review.split("\n")
        fixes = [l for l in lines if any(k in l for k in ["🔴", "❌", "修复", "问题"])]
        return "\n".join(fixes[:10]) if fixes else review[:500]
