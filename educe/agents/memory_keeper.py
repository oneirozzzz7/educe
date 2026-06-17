from __future__ import annotations

import json
import time
import uuid
from typing import AsyncIterator

from educe.core.agent import BaseAgent
from educe.core.message import Message, MessageType, WorkContext
from educe.memory.store import MemoryStore, MemoryEntry
from educe.skills.registry import SkillRegistry, Skill


class MemoryKeeperAgent(BaseAgent):
    name = "memory_keeper"
    role = "记忆守护者"
    description = """你是DeepForge的记忆守护者Agent，负责：
1. 整理本次项目的关键知识和经验
2. 沉淀可复用的模式、模板和技能
3. 更新知识库，让DeepForge越用越强
4. 生成项目总结文档

你的使命是让每次项目经验都成为下一次的养分。"""

    def __init__(self, *args, memory_store: MemoryStore | None = None, skill_registry: SkillRegistry | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory_store = memory_store or MemoryStore()
        self.skill_registry = skill_registry or SkillRegistry()

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        messages = [{"role": "user", "content": self._build_prompt(message, context)}]

        response = await self.call_model(messages, context)

        self._save_memories(context, response)

        context.add_artifact("project_summary", response)

        yield self.emit("user", response)

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        artifacts_summary = "\n".join(
            f"- {k}: {'有' if v else '无'}" for k, v in context.artifacts.items()
        )
        existing_skills = [s.name for s in self.skill_registry.list_all()]
        memory_stats = self.memory_store.stats()

        return f"""## 项目完成，需要知识沉淀
### 用户原始需求
{context.user_request}

### 产出物概览
{artifacts_summary}

### 群像用户反馈
{context.artifacts.get('crowd_feedback', '无')}

### 代码审查报告
{context.artifacts.get('review_report', '无')}

### 现有知识库状态
- 记忆条目数: {memory_stats.get('total', 0)}
- 现有技能: {', '.join(existing_skills[:20])}

## 你的任务
整理本次项目经验，输出以下内容：

### 1. 项目总结
- 做了什么
- 最终效果如何
- 耗时/效率评估

### 2. 知识沉淀（以JSON格式输出，方便存储）
提炼可复用的知识点，格式：
```json
[
  {{
    "category": "pattern/skill/feedback/lesson",
    "title": "知识点标题",
    "content": "详细内容",
    "tags": ["标签1", "标签2"]
  }}
]
```

### 3. 技能提炼
如果本次项目形成了可复用的工作流，提炼为技能模板：
```json
{{
  "name": "技能名称",
  "description": "技能描述",
  "tags": ["标签"],
  "pipeline": ["agent1", "agent2"],
  "prompt_template": "模板内容"
}}
```

### 4. 改进建议
对DeepForge自身工作流程的改进建议

请确保提炼的知识具有普适性，可以帮助未来的项目。"""

    def _save_memories(self, context: WorkContext, response: str) -> None:
        import re
        json_blocks = re.findall(r'```json\s*(.*?)```', response, re.DOTALL)

        for block in json_blocks:
            try:
                data = json.loads(block)
                if isinstance(data, list):
                    for item in data:
                        if "title" in item and "content" in item:
                            entry = MemoryEntry(
                                id=uuid.uuid4().hex[:12],
                                category=item.get("category", "pattern"),
                                title=item["title"],
                                content=item["content"],
                                tags=item.get("tags", []),
                                source="auto",
                            )
                            self.memory_store.add(entry)
                elif isinstance(data, dict) and "name" in data:
                    skill = Skill(
                        name=data["name"],
                        description=data.get("description", ""),
                        tags=data.get("tags", []),
                        pipeline=data.get("pipeline", []),
                        prompt_template=data.get("prompt_template", ""),
                        source="auto",
                    )
                    self.skill_registry.save_skill(skill)
            except (json.JSONDecodeError, Exception):
                pass
