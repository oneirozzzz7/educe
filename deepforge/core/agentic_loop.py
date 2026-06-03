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
- 写完代码后用run验证一次（HTML提取JS后用node --check验证语法）
- 如果报错就修复并重新验证
- 验证通过后立即结束，不要重复验证
- 每次只调用一个工具
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
        on_chunk: Callable[[str], None] | None = None,
        stream_model_fn: Callable | None = None,
        on_tool_event: Callable[[dict], None] | None = None,
    ) -> dict[str, str]:
        """
        主循环。模型自主决定写什么/运行什么/修什么。
        on_tool_event: 结构化事件推送，让前端展示每一步动作和结果。
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        messages: list[dict] = [
            {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_request},
        ]

        for turn in range(self.max_turns):
            self.turns_used = turn + 1

            if turn == 0 and stream_model_fn and on_chunk:
                response = await self._stream_call(messages, stream_model_fn, on_chunk)
            else:
                response = await call_model_fn(messages)

            # 提取模型的思考文本（action块之前的内容）
            thinking = self._extract_thinking(response)
            if thinking and on_tool_event:
                on_tool_event({"event": "thinking", "content": thinking})

            actions = self._parse_actions(response)

            if not actions:
                if on_tool_event:
                    on_tool_event({"event": "done",
                                  "files": list(self.files_written.keys()),
                                  "turns": self.turns_used})
                break

            results = []
            for action in actions:
                # 动作开始事件
                if on_tool_event:
                    evt = {"event": action["type"]}
                    if action["type"] == "write_file":
                        lines = action["body"].split("\n")
                        for l in lines:
                            if l.startswith("path:"):
                                evt["file"] = l.split(":", 1)[1].strip()
                                break
                    elif action["type"] == "run":
                        evt["command"] = action["body"].strip()[:100]
                    on_tool_event(evt)

                result = await self._execute(action)
                results.append(result)

                if result.file_written:
                    content = (
                        self.output_dir / result.file_written
                    ).read_text(encoding="utf-8")
                    self.files_written[result.file_written] = content

                # 动作结果事件
                if on_tool_event:
                    evt = {
                        "event": "{}_result".format(action["type"]),
                        "success": result.success,
                        "output": result.output[:300],
                    }
                    if result.file_written:
                        evt["file"] = result.file_written
                        evt["size"] = len(content.encode("utf-8"))
                    on_tool_event(evt)

            result_text = "\n\n".join(
                "工具 {} 执行结果:\n{}".format(r.tool, r.output) for r in results
            )

            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": result_text})

        return self.files_written

    @staticmethod
    def _extract_thinking(response: str) -> str:
        """提取action块之前的文本作为模型的思考"""
        first_action = response.find("```action:")
        if first_action <= 0:
            return ""
        text = response[:first_action].strip()
        if len(text) < 5:
            return ""
        return text[:200]

    async def _stream_call(
        self,
        messages: list[dict],
        stream_fn: Callable,
        on_chunk: Callable[[str], None],
    ) -> str:
        """真正的streaming调用——每个token立即推给前端"""
        full = ""
        async for chunk in stream_fn(messages):
            full += chunk
            on_chunk(chunk)
        return full

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

        # Adaptive timeout: data-heavy scripts get more time
        timeout = self.exec_timeout
        if "python" in cmd:
            # Read the script to detect heavy imports
            parts = cmd.split()
            script_name = parts[1] if len(parts) > 1 else ""
            if script_name:
                script_path = self.output_dir / script_name
                if script_path.exists():
                    try:
                        src = script_path.read_text(encoding="utf-8", errors="ignore")[:2000]
                        if any(lib in src for lib in ("pandas", "matplotlib", "numpy", "scipy", "sklearn", "plotly", "seaborn", "requests")):
                            timeout = max(timeout, 60)
                    except Exception:
                        pass

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.output_dir),
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
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
