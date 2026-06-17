from __future__ import annotations

from typing import AsyncIterator

from educe.core.agent import BaseAgent
from educe.core.message import Message, MessageType, WorkContext


class ArchitectAgent(BaseAgent):
    name = "architect"
    role = "架构师"
    description = """你是DeepForge的架构师Agent，负责：
1. 根据PRD设计技术架构方案
2. 进行技术选型（语言、框架、数据库等）
3. 设计系统架构（模块划分、接口定义）
4. 将开发工作拆解为具体的编码任务
5. 输出详细的技术设计文档

你的输出应包含：
- 技术选型及理由
- 系统架构图（文本描述）
- 目录结构设计
- 核心模块设计
- API/接口定义
- 数据模型设计
- 编码任务拆解"""

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        messages = [{"role": "user", "content": self._build_prompt(message, context)}]

        response = await self.call_model(messages, context)

        context.add_artifact("architecture", response)

        yield self.emit("user", response)

        yield self.handoff(
            "engineer",
            f"## 架构师移交\n\n"
            f"### 用户原始需求\n{context.user_request}\n\n"
            f"### 产品设计（PRD）\n{context.artifacts.get('prd', '无')}\n\n"
            f"### 技术架构设计\n{response}\n\n"
            f"请严格按照以上架构设计完成编码实现。",
        )

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        prd = context.artifacts.get("prd", "")

        return f"""## 输入信息
### 用户原始需求
{context.user_request}

### 产品需求文档（PRD）
{prd}

### 产品经理移交内容
{message.content}

## 你的任务
基于以上信息，输出一份完整的技术架构设计文档：

### 1. 技术选型
- 编程语言及版本
- 框架/库的选择及理由
- 数据库/存储方案（如需要）
- 第三方服务/API（如需要）

**选型原则**：优先选择轻量、成熟、社区活跃的方案

### 2. 系统架构
- 整体架构描述
- 核心模块及职责
- 模块间依赖关系

### 3. 目录结构
用tree格式输出完整的项目目录结构

### 4. 核心模块设计
每个模块包含：
- 职责描述
- 关键类/函数签名
- 输入输出定义

### 5. API/接口设计（如适用）
RESTful API或CLI命令定义

### 6. 数据模型（如适用）
数据库表结构或数据结构定义

### 7. 编码任务拆解
按实现顺序排列，每个任务包含：
- 任务标题
- 涉及文件
- 实现要点
- 预计代码量

请用markdown格式输出，确保工程师可以直接照此实现。"""
