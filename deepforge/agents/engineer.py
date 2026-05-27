from __future__ import annotations

import json
import re
from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.tools.toolbox import ToolBox


class EngineerAgent(BaseAgent):
    name = "engineer"
    role = "全栈工程师"
    description = """你是DeepForge的全栈工程师Agent，负责：
1. 根据架构设计文档进行编码实现
2. 分步骤创建文件——每次专注一个模块，确保质量
3. 编写高质量、可运行的代码
4. 修复审查反馈中指出的问题

核心策略：一次只做一件事，做好做完整。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.toolbox = ToolBox()

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        iteration = message.data.get("iteration", 1)
        is_fix_mode = iteration > 1 and "审查反馈" in message.content

        if is_fix_mode:
            prompt = self._build_fix_prompt(message, context)
        else:
            prompt = self._build_prompt(message, context)

        messages = [{"role": "user", "content": prompt}]
        response = await self.call_model(messages, context)

        files = self._extract_files(response)
        if files:
            write_results = []
            for filepath, content in files.items():
                result = await self.toolbox.write_file(filepath, content)
                write_results.append(result)

            prev_files = context.artifacts.get("code_files", [])
            all_files = list(set(prev_files + list(files.keys())))
            context.add_artifact("code_files", all_files)
            context.add_artifact("engineer_output", response)

            summary = f"{response}\n\n---\n### 文件写入结果\n" + "\n".join(write_results)
            yield self.emit("user", summary)
        else:
            context.add_artifact("engineer_output", response)
            yield self.emit("user", response)

        if not self._is_iterative_mode(context):
            yield self.handoff(
                "reviewer",
                f"## 工程师移交\n\n"
                f"### 用户原始需求\n{context.user_request}\n\n"
                f"### 技术架构\n{context.artifacts.get('architecture', '无')[:2000]}\n\n"
                f"### 实现代码\n{response}\n\n"
                f"### 创建的文件\n{json.dumps(list(files.keys()) if files else [], ensure_ascii=False)}\n\n"
                f"请对以上代码进行全面审查。",
            )

    def _is_iterative_mode(self, context: WorkContext) -> bool:
        return context.metadata.get("iteration", 0) > 0

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        architecture = context.artifacts.get("architecture", "")
        prd = context.artifacts.get("prd", "")

        arch_summary = architecture[:4000] if len(architecture) > 4000 else architecture

        return f"""## 输入信息
### 用户原始需求
{context.user_request}

### 产品需求文档（摘要）
{prd[:2000] if len(prd) > 2000 else prd}

### 技术架构设计
{arch_summary}

### 架构师移交内容
{message.content[:2000]}

## 你的任务
严格按照技术架构设计完成编码工作。

### ⚠️ 关键编码策略（必须遵守）
**弱模型友好原则**：不要试图一次写完所有文件。按以下优先级逐步输出：

1. **先写骨架**：项目配置文件（pyproject.toml/requirements.txt）+ 目录结构 + __init__.py
2. **再写核心模块**：数据模型（Pydantic Model）+ 配置加载
3. **然后写业务逻辑**：主处理流程 + 工具函数
4. **最后写入口**：CLI入口 + main函数

每个文件必须：
- 代码100%完整，禁止省略（如"其余代码类似"）
- 包含必要的import
- 有if __name__=="__main__"的简单自测

### 输出格式
每个文件使用以下格式（filepath:后面是完整路径）：

```filepath:文件路径
完整代码内容
```

### 最后附上
1. 依赖安装命令
2. 运行命令
3. 已实现的文件清单（checklist形式，标注✅已完成/❌未完成）"""

    def _build_fix_prompt(self, message: Message, context: WorkContext) -> str:
        prev_output = context.artifacts.get("engineer_output", "")
        existing_files = context.artifacts.get("code_files", [])

        return f"""## 修复任务

### 审查反馈
{message.content}

### 已有文件清单
{json.dumps(existing_files, ensure_ascii=False)}

### 上一轮代码（参考）
{prev_output[:4000]}

## 你的任务
根据审查反馈修复问题。

### 修复策略
1. **只修复被指出的问题**，不要重写没有问题的代码
2. **补全缺失的文件**——如果审查指出某文件缺失，必须完整输出该文件
3. **修复bug**——给出修复后的完整文件（不要只给diff）
4. 每个修改/新增文件使用 ```filepath:路径 格式

### 输出
1. 修复了哪些问题（对照审查反馈逐条说明）
2. 修改/新增的完整文件代码
3. 修复后的文件清单"""

    def _extract_files(self, content: str) -> dict[str, str]:
        files = {}
        pattern = r'```(?:filepath:)?([^\n]+)\n(.*?)```'
        matches = re.finditer(pattern, content, re.DOTALL)

        skip_prefixes = (
            "http", "bash", "shell", "json", "yaml", "yml", "markdown", "md",
            "text", "txt", "sql", "python", "javascript", "typescript",
            "html", "css", "toml", "xml", "diff", "log", "csv",
        )

        for match in matches:
            filepath = match.group(1).strip()
            code = match.group(2).strip()

            if not ("/" in filepath or "." in filepath):
                continue
            if filepath.lower().startswith(skip_prefixes):
                continue
            if len(code) < 10:
                continue

            files[filepath] = code

        return files
