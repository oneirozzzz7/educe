from __future__ import annotations

from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    role = "代码审查专家"
    description = """你是DeepForge的代码审查Agent，负责：
1. 对工程师产出的代码进行全面审查
2. 检查代码质量、安全性、性能
3. 验证代码是否符合架构设计
4. 验证代码是否满足产品需求
5. 输出审查报告和修改建议

审查维度：
- 正确性：逻辑是否正确，是否有bug
- 安全性：是否有安全漏洞（XSS、SQL注入、敏感信息泄露等）
- 性能：是否有性能问题
- 可维护性：代码是否清晰、易于维护
- 完整性：是否遗漏了功能"""

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        messages = [{"role": "user", "content": self._build_prompt(message, context)}]

        response = await self.call_model(messages, context)

        context.add_artifact("review_report", response)

        yield self.emit("user", response)

        yield self.handoff(
            "crowd_user",
            f"## 审查专家移交\n\n"
            f"### 用户原始需求\n{context.user_request}\n\n"
            f"### 产品设计\n{context.artifacts.get('prd', '无')}\n\n"
            f"### 审查报告\n{response}\n\n"
            f"请以各类用户的视角对产品进行体验评估。",
        )

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        engineer_output = context.artifacts.get("engineer_output", "")
        architecture = context.artifacts.get("architecture", "")
        prd = context.artifacts.get("prd", "")

        return f"""## 输入信息
### 用户原始需求
{context.user_request}

### 产品需求文档
{prd}

### 技术架构设计
{architecture}

### 工程师实现代码
{engineer_output}

### 工程师移交内容
{message.content}

## 你的任务
对工程师提交的代码进行全面审查，输出审查报告：

### 审查清单
1. **正确性检查**
   - 逻辑是否正确
   - 是否有明显bug
   - 边界情况处理是否完善

2. **需求符合性**
   - 是否实现了PRD中的所有功能
   - 是否符合架构设计

3. **安全性检查**
   - 输入验证
   - XSS/注入风险
   - 敏感信息处理
   - 权限控制

4. **性能检查**
   - 是否有性能瓶颈
   - 资源使用是否合理

5. **代码质量**
   - 可读性
   - 可维护性
   - 是否遵循最佳实践

### 输出格式
- 🟢 通过：无问题
- 🟡 建议：可以改进但不阻塞
- 🔴 必须修复：影响功能或安全的问题

对于每个问题，给出：
1. 问题描述
2. 所在位置
3. 修复建议
4. 修复后的代码（如适用）

最后给出总体评分（1-10分）和总结。"""
