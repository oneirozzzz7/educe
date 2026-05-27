from __future__ import annotations

import random
from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext


CROWD_PERSONAS = [
    {
        "name": "小白用户-小明",
        "profile": "大学生，完全不懂技术，第一次使用这类产品",
        "focus": "易用性、引导、报错提示是否友好",
        "style": "会问很多'为什么'，容易被复杂操作劝退",
    },
    {
        "name": "产品经理-Lisa",
        "profile": "3年经验的产品经理，熟悉互联网产品",
        "focus": "功能完整性、交互逻辑、用户体验细节",
        "style": "会从产品视角提出系统性建议，关注用户路径",
    },
    {
        "name": "资深开发-老王",
        "profile": "10年经验的全栈开发，技术极客",
        "focus": "技术实现质量、性能、扩展性、API设计",
        "style": "会深入技术细节，关注架构合理性",
    },
    {
        "name": "设计师-小艺",
        "profile": "UI/UX设计师，注重视觉和交互",
        "focus": "视觉效果、交互动效、信息层级、一致性",
        "style": "会从审美和交互角度提出建议",
    },
    {
        "name": "创业者-Alex",
        "profile": "连续创业者，关注产品的商业价值",
        "focus": "核心价值、差异化、市场定位、变现可能",
        "style": "会从商业角度评估产品，关注MVP和增长",
    },
    {
        "name": "无障碍用户-小芳",
        "profile": "视力不太好的用户，依赖辅助功能",
        "focus": "可访问性、字体大小、对比度、键盘操作",
        "style": "会测试各种辅助功能，关注包容性设计",
    },
]


class CrowdUserAgent(BaseAgent):
    name = "crowd_user"
    role = "群像用户内测团"
    description = """你是DeepForge的群像用户Agent，模拟多种不同背景的用户来内测产品。
你会从多个用户视角出发，提出真实、多样化的产品改进建议。
每个模拟用户有不同的背景、关注点和沟通风格。"""

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        selected = random.sample(CROWD_PERSONAS, min(4, len(CROWD_PERSONAS)))

        messages = [{"role": "user", "content": self._build_prompt(message, context, selected)}]

        response = await self.call_model(messages, context)

        context.add_artifact("crowd_feedback", response)

        yield self.emit("user", response)

        yield self.handoff(
            "memory_keeper",
            f"## 群像用户移交\n\n"
            f"### 用户原始需求\n{context.user_request}\n\n"
            f"### 产品设计\n{context.artifacts.get('prd', '无')}\n\n"
            f"### 代码审查报告\n{context.artifacts.get('review_report', '无')}\n\n"
            f"### 用户反馈\n{response}\n\n"
            f"请整理本次项目的知识沉淀。",
        )

    def _build_prompt(self, message: Message, context: WorkContext, personas: list[dict]) -> str:
        prd = context.artifacts.get("prd", "")
        review = context.artifacts.get("review_report", "")
        engineer_output = context.artifacts.get("engineer_output", "")

        persona_desc = "\n\n".join(
            f"### 用户{i+1}: {p['name']}\n"
            f"- **背景**: {p['profile']}\n"
            f"- **关注**: {p['focus']}\n"
            f"- **风格**: {p['style']}"
            for i, p in enumerate(personas)
        )

        return f"""## 产品信息
### 用户原始需求
{context.user_request}

### 产品设计
{prd}

### 实现代码概要
{engineer_output[:2000] if engineer_output else '无'}

### 代码审查报告
{review}

## 你的角色
你需要同时扮演以下{len(personas)}个不同用户，从各自视角对产品进行体验和评估：

{persona_desc}

## 输出要求
按以下格式输出每个用户的反馈：

---
#### 👤 [用户名]
**整体评价**: ⭐⭐⭐⭐ (1-5星)

**优点**:
- ...

**问题与建议**:
1. [问题描述] → [改进建议]
2. ...

**最想要的新功能**:
- ...
---

最后，输出一份**综合改进清单**，按优先级排列所有用户的建议，标注：
- 🔴 必须修复（多人提到/影响核心体验）
- 🟡 建议优化（提升体验但不阻塞使用）
- 🟢 锦上添花（未来版本考虑）"""
