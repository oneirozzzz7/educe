from __future__ import annotations

from typing import AsyncIterator

from educe.core.agent import BaseAgent
from educe.core.message import Message, MessageType, WorkContext


class ProductManagerAgent(BaseAgent):
    name = "product_manager"
    role = "产品经理"
    description = """你是DeepForge的产品经理Agent，负责：
1. 将项目经理的计划转化为详细的产品设计方案
2. 定义功能清单、用户故事和验收标准
3. 设计用户交互流程和界面结构
4. 输出PRD（产品需求文档）

你的输出应包含：
- 产品概述
- 核心功能列表及优先级
- 用户故事（User Stories）
- 页面/界面结构（如适用）
- 验收标准
- 非功能性需求（性能、安全等）"""

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        messages = [{"role": "user", "content": self._build_prompt(message, context)}]

        response = await self.call_model(messages, context)

        context.add_artifact("prd", response)

        yield self.emit("user", response)

        yield self.handoff(
            "architect",
            f"## 产品经理移交\n\n"
            f"### 用户原始需求\n{context.user_request}\n\n"
            f"### 产品设计方案（PRD）\n{response}\n\n"
            f"请基于以上PRD完成技术架构设计。",
        )

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        project_plan = context.artifacts.get("project_plan", "")

        return f"""## 输入信息
### 用户原始需求
{context.user_request}

### 项目经理的规划
{project_plan}

### 项目经理移交内容
{message.content}

## 你的任务
基于以上信息，输出一份完整的产品需求文档（PRD），包含：

### 1. 产品概述
简要描述产品是什么、解决什么问题、目标用户

### 2. 核心功能列表
按优先级P0/P1/P2排列，每个功能包含：
- 功能名称
- 功能描述
- 用户价值

### 3. 用户故事
以"作为XX，我想要XX，以便XX"的格式

### 4. 界面/交互设计
- 页面结构（如果是Web/App）
- 命令结构（如果是CLI工具）
- 关键交互流程

### 5. 验收标准
每个核心功能对应的验收条件

### 6. 非功能性需求
性能、安全、兼容性等要求

请用markdown格式输出，内容要具体可执行，方便架构师直接使用。"""
