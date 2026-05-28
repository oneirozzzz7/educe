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
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.core.observer import Observer
from deepforge.core.task_store import TaskStore
from deepforge.core.event_bus import EventBus, Event, EventType

console = Console()

HIDDEN_FROM_USER = {"memory_keeper", "crowd_user"}


class Orchestrator:
    def __init__(self, config: DeepForgeConfig, max_iterations: int = 3):
        self.config = config
        self.agents: dict[str, BaseAgent] = {}
        self.context = WorkContext()
        self.max_iterations = max_iterations
        self.observer = Observer()
        self.task_store = TaskStore()
        self.bus = EventBus()

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
        if msg.sender in HIDDEN_FROM_USER:
            return
        icon = {"project_manager": "🎯", "product_manager": "📋", "architect": "🏗️",
                "engineer": "💻", "reviewer": "🔍", "assistant": "💬"}.get(msg.sender, "🤖")
        console.print(Panel(Markdown(msg.content[:500]), title=f"{icon} {msg.sender}", border_style="cyan", padding=(0, 1)))

    # ═══════════════════════════════════════
    #  唯一入口
    # ═══════════════════════════════════════

    async def run(self, user_input: str) -> WorkContext:
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

    async def _smart_decide(self, user_input: str) -> dict:
        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "请先配置模型。"}
        try:
            result = await client.chat(
                messages=[
                    {"role": "system", "content": (
                        "你是DeepForge助手。判断用户需求：\n"
                        "- 需要编程做大型系统(多页面/前后端分离/多模块)→只回复：NEED_CODE_COMPLEX\n"
                        "- 需要编程做单页面工具/网页/游戏/编辑器/可视化→只回复：NEED_CODE_SIMPLE\n"
                        "- 其他→直接输出完整内容\n\n"
                        "单HTML能完成的都是SIMPLE。只有多服务协作才是COMPLEX。"
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
            return {"action": "reply", "content": result}
        except Exception as e:
            return {"action": "reply", "content": f"出错了: {e}"}

    # ═══════════════════════════════════════
    #  快速编码（直接走工程师）
    # ═══════════════════════════════════════

    async def _run_quick_code(self, user_input: str) -> WorkContext:
        pipeline_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user", content="__PIPELINE_START__")
        self._notify(pipeline_msg)

        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        output, _ = await self._run_agent("engineer", user_input, "user", timeout=120)

        validation = self.context.artifacts.get("validation", {})
        if validation and not validation.get("passed", True):
            output, _ = await self._run_agent("engineer",
                f"上次代码有问题({validation.get('summary','')})\n原始需求：{user_input}\n请修复。",
                "reviewer", data={"iteration": 2}, timeout=120)

        has_output = bool(self.context.artifacts.get("code_files"))
        self.observer.finish_task(success=has_output, project_type=self.context.artifacts.get("project_type", ""),
                                 file_count=len(self.context.artifacts.get("code_files", [])))
        self.task_store.save_from_context(task_id, self.context)

        if not has_output:
            self._send_fail()
        return self.context

    # ═══════════════════════════════════════
    #  完整Pipeline（并行优化）
    # ═══════════════════════════════════════

    async def _run_code_pipeline(self, user_input: str) -> WorkContext:
        pipeline_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user", content="__PIPELINE_START__")
        self._notify(pipeline_msg)

        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        # Phase 1: PM + PD 并行
        pm_task = self._run_agent("project_manager", user_input, "user", timeout=60)
        pd_task = self._run_agent("product_manager", user_input, "user", timeout=60)
        (pm_out, _), (pd_out, _) = await asyncio.gather(pm_task, pd_task)

        combined = f"## 项目规划\n{pm_out[:2000]}\n\n## 产品设计\n{pd_out[:2000]}"

        # Phase 2: 架构师（依赖PM+PD）
        arch_out, _ = await self._run_agent("architect", combined, "product_manager", timeout=60)

        # Phase 3: 工程师迭代
        current_content = arch_out
        current_sender = "architect"

        for iteration in range(1, self.max_iterations + 1):
            console.print(f"\n[bold yellow]🔄 迭代 {iteration}/{self.max_iterations}[/bold yellow]")

            eng_out, _ = await self._run_agent("engineer", current_content, current_sender,
                                               data={"iteration": iteration}, timeout=120)

            validation = self.context.artifacts.get("validation", {})
            if validation and not validation.get("passed", True) and iteration < self.max_iterations:
                current_content = f"验证失败: {validation.get('summary','')}\n请修复并输出完整代码。"
                current_sender = "reviewer"
                continue

            rev_out, _ = await self._run_agent("reviewer",
                f"工程师第{iteration}轮产出:\n{eng_out[:3000]}", "engineer",
                data={"iteration": iteration}, timeout=60)

            if self._review_passed(rev_out):
                console.print("[green]✅ 审查通过[/green]")
                break
            elif iteration < self.max_iterations:
                console.print("[red]🔴 审查未通过，回退修改[/red]")
                fix = self._extract_fixes(rev_out)
                current_content = f"审查反馈:\n{fix}\n\n请修复后输出完整代码。"
                current_sender = "reviewer"

        has_output = bool(self.context.artifacts.get("code_files"))

        if has_output:
            # Phase 4: 群测 + 记忆 并行
            crowd_task = self._run_agent("crowd_user", eng_out[:2000], "reviewer", timeout=60)
            mem_task = self._run_agent("memory_keeper", eng_out[:2000], "reviewer", timeout=60)
            await asyncio.gather(crowd_task, mem_task, return_exceptions=True)

        self.observer.finish_task(success=has_output, project_type=self.context.artifacts.get("project_type", ""),
                                 file_count=len(self.context.artifacts.get("code_files", [])))
        self.task_store.save_from_context(task_id, self.context)

        if not has_output:
            self._send_fail()
        return self.context

    # ═══════════════════════════════════════
    #  修改已有产出物
    # ═══════════════════════════════════════

    async def _run_followup(self, user_input: str) -> WorkContext:
        prev = self.context.artifacts.get("engineer_output", "")
        await self._run_agent("engineer",
            f"用户要求修改：{user_input}\n\n当前代码：\n{prev[:4000]}\n\n输出修改后的完整文件。",
            "user", timeout=120)
        return self.context

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

        msg = Message(
            type=MessageType.TASK if sender != "user" else MessageType.USER_INPUT,
            sender=sender, receiver=agent_name, content=content,
            data=data or {},
        )
        self.context.add_message(msg)

        output = content
        try:
            response_gen = agent.handle(msg, self.context)
            async for response in asyncio.wait_for(self._drain(response_gen), timeout=timeout):
                self.context.add_message(response)
                if response.sender not in HIDDEN_FROM_USER:
                    self._notify(response)
                self._display(response)
                output = response.content

                await self.bus.emit(Event(
                    type=EventType.AGENT_DONE if response.type != MessageType.HANDOFF else EventType.CONTENT_READY,
                    sender=agent_name,
                    data={"content": output[:200], "has_files": bool(self.context.artifacts.get("code_files"))},
                ))

            self.observer.finish_agent(agent_name, success=True, summary=output[:80])
        except asyncio.TimeoutError:
            console.print(f"[yellow]⚠ [{agent_name}] 超时({timeout}s)[/yellow]")
            self.observer.finish_agent(agent_name, success=False, error=f"timeout({timeout}s)")
        except Exception as e:
            console.print(f"[red]⚠ [{agent_name}] 失败: {e}[/red]")
            self.observer.finish_agent(agent_name, success=False, error=str(e))
            if agent_name == "engineer":
                raise

        return output, agent_name

    async def _drain(self, gen):
        async for item in gen:
            yield item

    # ═══════════════════════════════════════
    #  工具方法
    # ═══════════════════════════════════════

    def _get_client(self):
        if not self.agents:
            return None
        return next(iter(self.agents.values())).model_client

    def _review_passed(self, review: str) -> bool:
        for s in ["🔴", "❌", "必须修复", "不通过", "严重问题"]:
            if s in review:
                return False
        m = re.search(r'(?:评分|score)[：:\s]*(\d+)', review)
        if m:
            return int(m.group(1)) >= 7
        for s in ["✅ 通过", "✅ 审查通过", "审查通过"]:
            if s in review:
                return True
        return False

    def _extract_fixes(self, review: str) -> str:
        lines = review.split("\n")
        fixes = [l for l in lines if any(k in l for k in ["🔴", "❌", "修复", "问题"])]
        return "\n".join(fixes[:10]) if fixes else review[:500]

    def _send_fail(self):
        msg = Message(type=MessageType.RESULT, sender="system", receiver="user",
                      content="未能生成可用的产出物，请更具体描述需求。")
        self.context.add_message(msg)
        self._notify(msg)
