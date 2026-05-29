"""
Planner Agent — 任务拆解+经验复用
复杂任务拆成子任务，查记忆/Skill匹配已验证模板
"""
from __future__ import annotations

from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.core.knowledge import LayeredCache


class PlannerAgent(BaseAgent):
    name = "planner"
    role = "Planner"
    description = "任务拆解和经验复用——复杂任务才需要"

    def __init__(self, *args, knowledge=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.knowledge = knowledge or LayeredCache()

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        user_request = context.user_request

        # 查知识库
        recalled = self.knowledge.recall(user_request, max_results=3)
        knowledge_section = ""
        if recalled:
            knowledge_section = "\n已有相关经验：\n" + "\n".join(f"- {r[:80]}" for r in recalled)

        file_section = ""
        uploaded = context.metadata.get("uploaded_files", [])
        if uploaded:
            from deepforge.core.file_handler import format_for_prompt
            file_section = format_for_prompt(uploaded)

        prompt = f"""你是一个任务规划专家。将复杂需求拆解为可执行的子任务。

## 用户需求
{user_request}
{file_section}{knowledge_section}

## 输出格式
1. 分析需求复杂度
2. 拆解为2-5个子任务（每个子任务是一个独立可实现的单元）
3. 标注每个子任务的依赖关系
4. 给出实现顺序

## 规则
- 每个子任务必须可以独立生成一个文件
- 不要过度拆分——能一个文件搞定的就不要拆
- 优先使用已有经验中的模式

直接输出结构化计划，不要废话。"""

        messages = [{"role": "user", "content": prompt}]
        plan = await self.call_model(messages, context)

        context.add_artifact("plan", plan)
        yield self.emit("user", plan)
