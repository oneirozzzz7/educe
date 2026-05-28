from __future__ import annotations

import json
import re
from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext, Task, TaskStatus
from deepforge.memory.store import MemoryStore
from deepforge.skills.registry import SkillRegistry


class ProjectManagerAgent(BaseAgent):
    name = "project_manager"
    role = "项目经理"
    description = """你是DeepForge的项目经理Agent，负责：
1. 深度理解用户的真实意图，把模糊需求转化为精准可执行的项目计划
2. 分析项目复杂度，决定需要哪些Agent参与（不是每次都需要全部7个）
3. 拆解任务并制定详细的执行计划，包含依赖关系和优先级
4. 检索历史记忆和已有Skill，避免重复造轮子
5. 为每个Agent制定明确的交付标准和验收条件
6. 预判风险，制定应对策略

你的核心价值：让弱模型也能产出强结果——通过精准的任务拆解和约束条件。"""

    def __init__(self, *args, memory_store: MemoryStore | None = None, skill_registry: SkillRegistry | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory_store = memory_store
        self.skill_registry = skill_registry

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        related_memory = self._search_memory(context.user_request)
        related_skills = self._search_skills(context.user_request)

        messages = [{"role": "user", "content": self._build_prompt(message, context, related_memory, related_skills)}]

        response = await self.call_model(messages, context)

        tasks = self._extract_tasks(response)
        for task in tasks:
            context.tasks.append(task)

        pipeline_config = self._extract_pipeline(response)
        if pipeline_config:
            context.metadata["custom_pipeline"] = pipeline_config

        context.add_artifact("project_plan", response)

        yield self.emit("user", response)

        next_agent = pipeline_config[0] if pipeline_config else "product_manager"
        yield self.handoff(
            next_agent,
            f"## 项目经理移交\n\n"
            f"### 用户原始需求\n{context.user_request}\n\n"
            f"### 项目计划\n{response}\n\n"
            f"### 执行流水线\n{' → '.join(pipeline_config) if pipeline_config else '默认全流程'}\n\n"
            f"请基于以上信息开始你的工作。",
        )

    def _search_memory(self, query: str) -> str:
        if not self.memory_store:
            return ""
        results = self.memory_store.search(query, limit=5)
        if not results:
            return ""
        lines = ["### 相关历史记忆"]
        for entry in results:
            lines.append(f"- **{entry.title}** (使用{entry.usage_count}次, 成功率{entry.success_rate:.0%}): {entry.content[:100]}")
        return "\n".join(lines)

    def _search_skills(self, query: str) -> str:
        if not self.skill_registry:
            return ""
        results = self.skill_registry.search(query)
        if not results:
            return ""
        lines = ["### 可复用的Skill模板"]
        for skill in results[:5]:
            lines.append(f"- **{skill.name}**: {skill.description} (流水线: {' → '.join(skill.pipeline)})")
        return "\n".join(lines)

    def _build_prompt(self, message: Message, context: WorkContext, memory: str, skills: str) -> str:
        history = ""
        relevant = context.get_messages_for(self.name)
        if relevant:
            history = "\n\n### 历史对话\n" + "\n".join(
                f"[{m.sender}]: {m.content[:200]}" for m in relevant[-5:]
            )

        memory_section = f"\n\n{memory}" if memory else ""
        skills_section = f"\n\n{skills}" if skills else ""

        return f"""## 用户需求
{message.content}
{history}
{memory_section}
{skills_section}

## 你的任务
作为项目经理，你需要输出一份 **高质量、可执行的项目计划**。

### 第一步：需求深度分析
1. 用户说了什么（原文理解）
2. 用户真正想要什么（深层意图——用户可能是小白，表述不精确）
3. 用户没说但应该做的（补全遗漏需求）
4. 明确不做的（划定边界，防止范围蔓延）

### 第二步：项目复杂度评估
评估这个项目的复杂度等级：
- **S级（简单）**: 单文件、小功能 → 只需 工程师 + 审查
- **M级（中等）**: 多文件、需要设计 → 产品 + 架构 + 工程师 + 审查
- **L级（复杂）**: 完整产品 → 全部7个Agent
- **自定义**: 根据需求灵活组合Agent

输出建议的 **Agent执行流水线**，格式：
```pipeline
agent1 → agent2 → agent3
```

### 第三步：任务拆解（Task Breakdown）
用以下格式输出：
```tasks
T1: [任务标题] | 负责Agent: [agent名] | 优先级: P0/P1/P2 | 依赖: 无/T编号
T2: ...
```

### 第四步：每个Agent的交付标准
为流水线中每个Agent明确：
- 输入：它会收到什么
- 输出：它必须产出什么
- 验收条件：怎样算"做好了"
- 约束：不要做什么（防止跑偏）

### 第五步：风险预判
- 可能出什么问题
- 应对措施

### 第六步：成功标准
- 这个项目最终交付物是什么
- 怎样衡量"做好了"

### ⚠️ 来自历史项目的关键教训（必须遵守）
1. **先跑通再美化**：必须先让最小功能可运行，再补充高级功能
2. **脚手架≠MVP**：用户要的是可交互的产品，不是空白页面
3. **单文件优先**：如果需求是工具/网页类，优先做成单HTML文件
4. **验收必须可度量**：给出具体数字指标（如"5000行<100ms"），不要模糊描述

请用markdown格式输出完整计划。"""

    def _extract_tasks(self, content: str) -> list[Task]:
        tasks = []

        task_pattern = re.compile(r'T(\d+)\s*[:：]\s*(.+?)\s*\|\s*负责.*?[:：]\s*(\w+)\s*\|\s*优先级\s*[:：]\s*(P\d)', re.MULTILINE)
        matches = task_pattern.findall(content)
        if matches:
            for num, title, agent, priority in matches:
                tasks.append(Task(
                    title=title.strip(),
                    description=f"优先级: {priority}, 负责: {agent}",
                    assigned_to=agent,
                    created_by=self.name,
                ))
            return tasks[:20]

        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped and (stripped.startswith("- [ ]") or stripped.startswith("- ")):
                title = stripped.lstrip("- [ ]").strip()
                if title and len(title) > 2:
                    tasks.append(Task(title=title, description=title, created_by=self.name))
                    if len(tasks) >= 20:
                        break
        return tasks

    def _extract_pipeline(self, content: str) -> list[str]:
        pipeline_match = re.search(r'```pipeline\s*\n(.+?)\n```', content, re.DOTALL)
        if pipeline_match:
            pipeline_text = pipeline_match.group(1).strip()
            agents = [a.strip() for a in re.split(r'[→\->]+', pipeline_text)]
            valid_agents = ["project_manager", "product_manager", "architect", "engineer", "reviewer", "crowd_user", "memory_keeper"]
            return [a for a in agents if a in valid_agents]

        arrow_match = re.search(r'((?:project_manager|product_manager|architect|engineer|reviewer|crowd_user|memory_keeper)(?:\s*[→\->]+\s*(?:project_manager|product_manager|architect|engineer|reviewer|crowd_user|memory_keeper))+)', content)
        if arrow_match:
            agents = [a.strip() for a in re.split(r'[→\->]+', arrow_match.group(1))]
            return agents

        return []
