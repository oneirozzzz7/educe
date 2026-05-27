from __future__ import annotations

from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext


class SupervisorAgent(BaseAgent):
    name = "supervisor"
    role = "监工"
    description = """你是DeepForge的监工Agent，负责：
1. 审视所有Agent的工作质量，自主做出决策
2. 不需要等待人类确认——你就是决策者
3. 当发现问题时，直接指派修复任务
4. 持续监控框架健康度，发现退化及时干预
5. 决策原则：用户体验第一、代码质量第二、速度第三"""

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        messages = [{"role": "user", "content": self._build_prompt(message, context)}]
        response = await self.call_model(messages, context)
        context.add_artifact("supervisor_decision", response)
        yield self.emit("user", response)

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        stats = context.metadata.get("evolution_stats", {})
        recent_failures = context.metadata.get("recent_failures", [])

        return f"""## 监工决策请求

### 当前情况
{message.content}

### 框架统计
{stats if stats else '暂无统计数据'}

### 近期失败记录
{recent_failures if recent_failures else '无失败'}

## 你的职责
你是监工，不是建议者。你直接做决定。

### 决策模板（必须用这个格式输出）
```decision
action: [fix/skip/escalate/optimize]
target: [具体要修改什么]
reason: [一句话原因]
priority: [P0/P1/P2]
```

### 决策标准
- 如果测试通过率<90%: 立即修复工程师Agent的prompt
- 如果pipeline超时率>10%: 优化上下文长度截断策略
- 如果Skill生成失败: 简化Skill模板的prompt要求
- 如果一切正常: 选择下一个最有价值的优化方向

给出你的决策。"""
