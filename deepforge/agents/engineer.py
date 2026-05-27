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
2. 创建项目结构和所有必要文件
3. 编写高质量、可运行的代码
4. 编写单元测试
5. 确保代码可以直接运行

你的输出格式要求：
- 使用 ```文件路径 标记每个文件
- 代码必须完整，不能有省略
- 包含必要的配置文件（package.json、requirements.txt等）
- 附带运行说明"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.toolbox = ToolBox()

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        messages = [{"role": "user", "content": self._build_prompt(message, context)}]

        response = await self.call_model(messages, context)

        files = self._extract_files(response)
        if files:
            write_results = []
            for filepath, content in files.items():
                result = await self.toolbox.write_file(filepath, content)
                write_results.append(result)

            context.add_artifact("code_files", list(files.keys()))
            context.add_artifact("engineer_output", response)

            summary = f"{response}\n\n---\n### 文件写入结果\n" + "\n".join(write_results)
            yield self.emit("user", summary)
        else:
            context.add_artifact("engineer_output", response)
            yield self.emit("user", response)

        yield self.handoff(
            "reviewer",
            f"## 工程师移交\n\n"
            f"### 用户原始需求\n{context.user_request}\n\n"
            f"### 技术架构\n{context.artifacts.get('architecture', '无')}\n\n"
            f"### 实现代码\n{response}\n\n"
            f"### 创建的文件\n{json.dumps(list(files.keys()), ensure_ascii=False)}\n\n"
            f"请对以上代码进行全面审查。",
        )

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        architecture = context.artifacts.get("architecture", "")
        prd = context.artifacts.get("prd", "")

        return f"""## 输入信息
### 用户原始需求
{context.user_request}

### 产品需求文档
{prd}

### 技术架构设计
{architecture}

### 架构师移交内容
{message.content}

## 你的任务
严格按照技术架构设计，完成全部编码工作：

### 编码要求
1. **完整性**：所有文件的代码必须完整，不能有任何省略（如"// 其余代码类似"）
2. **可运行**：代码必须能直接运行，不能有语法错误
3. **规范性**：遵循对应语言的最佳实践和编码规范
4. **注释**：关键逻辑添加简要注释
5. **错误处理**：合理的错误处理和边界检查

### 输出格式
每个文件使用以下格式：

```filepath:文件路径
完整代码内容
```

### 额外输出
1. 依赖安装命令
2. 运行/启动命令
3. 关键功能说明

请确保代码质量，一次到位。"""

    def _extract_files(self, content: str) -> dict[str, str]:
        files = {}
        pattern = r'```(?:filepath:)?([^\n]+)\n(.*?)```'
        matches = re.finditer(pattern, content, re.DOTALL)
        for match in matches:
            filepath = match.group(1).strip()
            code = match.group(2).strip()
            if "/" in filepath or "." in filepath:
                if not filepath.startswith(("http", "bash", "shell", "json", "yaml", "markdown", "text", "sql", "python", "javascript", "typescript", "html", "css")):
                    files[filepath] = code
        return files
