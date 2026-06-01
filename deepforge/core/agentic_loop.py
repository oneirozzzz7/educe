"""
模型自主工具循环（Agentic Tool Loop）
核心机制：模型自己决定写什么、运行什么、修什么。框架只负责执行工具返回结果。
这是Claude Code的核心架构在弱模型上的实现。

工具调用格式（代码块）:
```action:write_file
path: filename.html
---
代码内容
```

```action:run
python script.py
```

```action:read_file
path: filename.html
```
"""
from __future__ import annotations

import re
import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable, Awaitable


@dataclass
class ToolResult:
    tool: str
    success: bool
    output: str
    file_written: str | None = None


AGENTIC_SYSTEM_PROMPT = """你是一个编程助手。你可以写代码、运行验证、读取文件。

可用工具:
1. write_file - 写文件到磁盘
2. run - 运行shell命令（python/node等）
3. read_file - 读取文件内容

调用格式（用代码块）:

写文件:
```action:write_file
path: 文件名
---
文件内容写在这里
```

运行命令:
```action:run
python 文件名.py
```

读文件:
```action:read_file
path: 文件名
```

重要规则:
- 写完代码后必须用run验证（HTML用node --check验证JS语法）
- 如果运行报错，修复代码并重新验证
- 确认代码正确后才能结束
- 每轮可以调用多个工具"""


class AgenticLoop:
    """模型自主工具循环。模型决定下一步，框架只执行。"""

    def __init__(self, output_dir: Path, max_turns: int = 10, exec_timeout: int = 10):
        self.output_dir = output_dir
        self.max_turns = max_turns
        self.exec_timeout = exec_timeout
        self.files_written: dict[str, str] = {}
        self.turns_used = 0

    async def run(
        self,
        user_request: str,
        call_model_fn: Callable[[list[dict]], Awaitable[str]],
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        """
        主循环：发需求给模型→模型输出(可能含action)→执行action→返回结果→模型继续
        返回最终写入的文件字典。
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        messages: list[dict] = [
            {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_request},
        ]

        for turn in range(self.max_turns):
            self.turns_used = turn + 1

            response = await call_model_fn(messages)

            actions = self._parse_actions(response)

            if not actions:
                if on_progress:
                    on_progress("完成")
                break

            results = []
            for action in actions:
                result = await self._execute(action)
                results.append(result)
                if result.file_written:
                    self.files_written[result.file_written] = (
                        self.output_dir / result.file_written
                    ).read_text(encoding="utf-8")

            result_text = "\n\n".join(
                "工具 {} 执行结果:\n{}".format(r.tool, r.output) for r in results
            )

            if on_progress:
                summary = ", ".join(r.tool for r in results)
                on_progress("Turn {}: {}".format(turn + 1, summary))

            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": result_text})

        return self.files_written

    def _parse_actions(self, response: str) -> list[dict]:
        """解析代码块格式的action调用"""
        actions = []
        pattern = r'```action:(\w+)\n([\s\S]*?)```'
        for match in re.finditer(pattern, response):
            action_type = match.group(1)
            body = match.group(2).strip()
            actions.append({"type": action_type, "body": body})
        return actions

    async def _execute(self, action: dict) -> ToolResult:
        action_type = action["type"]
        body = action["body"]

        if action_type == "write_file":
            return await self._exec_write(body)
        elif action_type == "run":
            return await self._exec_run(body)
        elif action_type == "read_file":
            return await self._exec_read(body)
        else:
            return ToolResult(tool=action_type, success=False,
                            output="未知工具: {}".format(action_type))

    async def _exec_write(self, body: str) -> ToolResult:
        lines = body.split("\n")
        path = ""
        content_start = 0

        for i, line in enumerate(lines):
            if line.startswith("path:"):
                path = line.split(":", 1)[1].strip()
            if line.strip() == "---":
                content_start = i + 1
                break

        if not path:
            if lines:
                path = lines[0].strip()
                content_start = 1

        content = "\n".join(lines[content_start:])
        if not path:
            return ToolResult(tool="write_file", success=False, output="缺少path参数")

        full_path = self.output_dir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

        return ToolResult(
            tool="write_file", success=True,
            output="已写入 {} ({}字符)".format(path, len(content)),
            file_written=path,
        )

    async def _exec_run(self, body: str) -> ToolResult:
        cmd = body.strip()
        if not cmd:
            return ToolResult(tool="run", success=False, output="命令为空")

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.output_dir),
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=self.exec_timeout
            )
            stdout = stdout_b.decode(errors="replace")[:1500]
            stderr = stderr_b.decode(errors="replace")[:1500]

            output = ""
            if stdout:
                output += "[stdout]\n{}\n".format(stdout)
            if stderr:
                output += "[stderr]\n{}\n".format(stderr)
            output += "[exit_code] {}".format(proc.returncode)

            return ToolResult(
                tool="run",
                success=proc.returncode == 0,
                output=output,
            )
        except asyncio.TimeoutError:
            return ToolResult(tool="run", success=False,
                            output="[error] 执行超时(>{}s)".format(self.exec_timeout))

    async def _exec_read(self, body: str) -> ToolResult:
        lines = body.split("\n")
        path = ""
        for line in lines:
            if line.startswith("path:"):
                path = line.split(":", 1)[1].strip()
                break
            if line.strip():
                path = line.strip()
                break

        if not path:
            return ToolResult(tool="read_file", success=False, output="缺少path参数")

        full_path = self.output_dir / path
        if not full_path.exists():
            return ToolResult(tool="read_file", success=False,
                            output="文件不存在: {}".format(path))

        content = full_path.read_text(encoding="utf-8", errors="replace")[:5000]
        return ToolResult(
            tool="read_file", success=True,
            output="[content]\n{}".format(content),
        )
