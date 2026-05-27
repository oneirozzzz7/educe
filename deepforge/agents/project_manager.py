from __future__ import annotations

from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext, Task, TaskStatus


class ProjectManagerAgent(BaseAgent):
    name = "project_manager"
    role = "项目经理"
    description = """你是DeepForge的项目经理Agent，负责：
1. 深度理解用户的真实意图和需求
2. 将模糊需求转化为清晰、可执行的项目计划
3. 拆解任务并分配给合适的Agent
4. 统筹全局进度，确保项目按计划推进
5. 协调各Agent之间的沟通和依赖

你的输出应包含：
- 对用户需求的理解摘要
- 项目整体规划
- 任务拆解和分配计划
- 下一步行动指令"""

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        messages = [{"role": "user", "content": self._build_prompt(message, context)}]

        response = await self.call_model(messages, context)

        tasks = self._extract_tasks(response)
        for task in tasks:
            context.tasks.append(task)

        context.add_artifact("project_plan", response)

        yield self.emit("user", response)

        yield self.handoff(
            "product_manager",
            f"## 项目经理移交\n\n"
            f"### 用户原始需求\n{context.user_request}\n\n"
            f"### 项目计划\n{response}\n\n"
            f"请基于以上信息完成产品设计。",
        )

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        history = ""
        relevant = context.get_messages_for(self.name)
        if relevant:
            history = "\n\n### 历史对话\n" + "\n".join(
                f"[{m.sender}]: {m.content[:200]}" for m in relevant[-5:]
            )

        return f"""## 用户需求
{message.content}

{history}

## 你的任务
1. 分析用户的真实意图——用户可能是小白，需求描述可能不精确，你需要补全和细化
2. 输出一份清晰的项目计划，包含：
   - 需求理解摘要（确保你理解了用户真正想要什么）
   - 项目范围（做什么、不做什么）
   - 技术方向建议
   - 任务拆解（按优先级排列）
   - 时间预估
3. 计划要具体、可执行，方便后续Agent直接使用

请用markdown格式输出。"""

    def _extract_tasks(self, content: str) -> list[Task]:
        tasks = []
        lines = content.split("\n")
        task_num = 0
        for line in lines:
            stripped = line.strip()
            if stripped and (stripped.startswith("- [ ]") or stripped.startswith("- ")):
                title = stripped.lstrip("- [ ]").strip()
                if title and len(title) > 2:
                    task_num += 1
                    tasks.append(Task(
                        title=title,
                        description=title,
                        created_by=self.name,
                    ))
                    if task_num >= 20:
                        break
        return tasks
