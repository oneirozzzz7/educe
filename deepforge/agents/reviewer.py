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
3. 验证代码是否符合架构设计和产品需求
4. 做出明确的通过/不通过判定
5. 不通过时输出结构化的修复指令

审查维度：正确性、安全性、性能、可维护性、完整性
判定标准：评分≥7分且无🔴必须修复项=通过"""

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        iteration = message.data.get("iteration", 1)
        messages = [{"role": "user", "content": self._build_prompt(message, context, iteration)}]

        response = await self.call_model(messages, context)

        context.add_artifact("review_report", response)

        yield self.emit("user", response)

        if not self._is_iterative_mode(context):
            yield self.handoff(
                "crowd_user",
                f"## 审查专家移交\n\n"
                f"### 用户原始需求\n{context.user_request}\n\n"
                f"### 产品设计\n{context.artifacts.get('prd', '无')}\n\n"
                f"### 审查报告\n{response}\n\n"
                f"请以各类用户的视角对产品进行体验评估。",
            )

    def _is_iterative_mode(self, context: WorkContext) -> bool:
        return context.metadata.get("iteration", 0) > 0

    def _build_prompt(self, message: Message, context: WorkContext, iteration: int) -> str:
        engineer_output = context.artifacts.get("engineer_output", "")
        architecture = context.artifacts.get("architecture", "")
        prd = context.artifacts.get("prd", "")

        iteration_context = ""
        if iteration > 1:
            prev_review = context.artifacts.get("review_report", "")
            iteration_context = f"""
### ⚠️ 这是第{iteration}轮审查
上一轮审查发现了问题，工程师已做修改。请重点检查：
1. 上一轮提出的🔴必须修复项是否全部修复
2. 修复过程中是否引入了新问题
3. 如果全部修复，可以给出通过判定

### 上一轮审查报告
{prev_review[:1500] if prev_review else '无'}
"""

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
{iteration_context}

## 你的任务
对工程师提交的代码进行全面审查，做出**明确的通过/不通过判定**。

### 审查清单

**1. 正确性检查**
- 逻辑是否正确，是否有明显bug
- 边界情况处理是否完善
- 是否实现了PRD中的所有核心功能

**2. 安全性检查**
- 输入验证、XSS/注入风险
- 敏感信息处理、权限控制

**3. 性能与质量**
- 是否有性能瓶颈
- 代码可读性、可维护性

**4. 完整性检查**
- 是否有遗漏的功能
- 配置文件、依赖声明是否完整
- 代码能否直接运行

### 输出格式（严格遵循）

#### 审查判定
**结果**: ✅ 审查通过 / ❌ 审查不通过
**总体评分**: X/10

#### 🔴 必须修复（不修复不能通过）
> 如果没有则写"无"

1. **[问题标题]**
   - 位置: [文件:行号 或 模块名]
   - 问题: [具体描述]
   - 修复方案: [明确的修复步骤]
   ```
   // 修复后的代码（如适用）
   ```

#### 🟡 建议优化
1. [问题] → [建议]

#### 🟢 通过项
- [做得好的点]

#### 总结
[一句话总结审查结论]"""
