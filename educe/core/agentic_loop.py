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
import logging

log = logging.getLogger("educe.core.agentic_loop")


@dataclass
class ToolResult:
    tool: str
    success: bool
    output: str
    file_written: str | None = None


@dataclass
class BuildResult:
    reason: str  # "complete" | "max_turns" | "empty_response" | "error"
    files: dict[str, str]
    turns: int
    errors: list[str]

    @property
    def success(self) -> bool:
        return bool(self.files) and self.reason in ("complete", "max_turns")


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

    def __init__(self, output_dir: Path, max_turns: int = 10, exec_timeout: int = 10,
                 max_context_chars: int = 50000):
        self.output_dir = output_dir
        self.max_turns = max_turns
        self.exec_timeout = exec_timeout
        self.max_context_chars = max_context_chars
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
        transcript=None,
    ) -> BuildResult:
        """
        主循环。模型自主决定写什么/运行什么/修什么。
        返回 BuildResult 包含结构化终止原因。
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._errors: list[str] = []

        system_content = AGENTIC_SYSTEM_PROMPT
        if transcript:
            system_content = transcript.render_for_model() + "\n\n" + AGENTIC_SYSTEM_PROMPT

        messages: list[dict] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_request},
        ]

        termination_reason = "max_turns"

        for turn in range(self.max_turns):
            self.turns_used = turn + 1

            # Context compression: compact old messages when total size exceeds threshold
            if turn > 0:
                self._compact_messages(messages)

            try:
                if turn == 0 and stream_model_fn and on_chunk:
                    response = await self._stream_call(messages, stream_model_fn, on_chunk)
                else:
                    response = await call_model_fn(messages)
            except Exception as e:
                self._errors.append("模型调用失败: {}".format(str(e)[:100]))
                termination_reason = "error"
                break

            if not response or not response.strip():
                self._errors.append("模型返回空响应")
                termination_reason = "empty_response"
                break

            # 提取模型的思考文本（action块之前的内容）
            thinking = self._extract_thinking(response)
            if thinking and on_tool_event:
                on_tool_event({"event": "thinking", "content": thinking})

            actions = self._parse_actions(response)

            if not actions:
                # Clean up <think> blocks before fallback extraction
                clean_response = response
                if "</think>" in clean_response:
                    clean_response = clean_response.split("</think>", 1)[-1].strip()
                # Fallback: model may have output code in ```filepath:xxx format without action prefix
                fallback_files = self._extract_files_fallback(clean_response)
                if fallback_files:
                    for fp, code in fallback_files.items():
                        full_path = self.output_dir / fp
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        full_path.write_text(code, encoding="utf-8")
                        self.files_written[fp] = code
                        if on_tool_event:
                            on_tool_event({"event": "write_file_result", "success": True,
                                          "file": fp, "size": len(code.encode("utf-8")),
                                          "output": "已写入 {} ({}字符)".format(fp, len(code))})
                            on_tool_event({"event": "step_code_content",
                                          "step": turn + 1, "code": code})

                termination_reason = "complete"
                if on_tool_event:
                    on_tool_event({"event": "done",
                                  "files": list(self.files_written.keys()),
                                  "turns": self.turns_used,
                                  "reason": termination_reason})
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

                if not result.success:
                    self._errors.append("{}: {}".format(result.tool, result.output[:100]))

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
                    if result.file_written:
                        on_tool_event({"event": "step_code_content",
                                       "step": turn + 1, "code": content})

            result_text = "\n\n".join(
                "工具 {} 执行结果:\n{}".format(r.tool, r.output) for r in results
            )

            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": result_text})

            # Update transcript with tool results
            if transcript:
                for r in results:
                    if r.file_written:
                        transcript.add("build", "model",
                            "写入 {} ({}字符)".format(r.file_written, len(self.files_written.get(r.file_written, ""))))
                    elif r.tool == "run":
                        status = "通过" if r.success else "失败"
                        transcript.add("build", "model", "验证{}".format(status))

        # Emit final done event with reason if we hit max_turns
        if termination_reason == "max_turns" and on_tool_event:
            on_tool_event({"event": "done",
                          "files": list(self.files_written.keys()),
                          "turns": self.turns_used,
                          "reason": termination_reason})

        return BuildResult(
            reason=termination_reason,
            files=self.files_written,
            turns=self.turns_used,
            errors=self._errors,
        )

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

    def _compact_messages(self, messages: list[dict], keep_recent: int = 3) -> None:
        """Sliding window compression. Keeps first 2 msgs (system+user) and last keep_recent turns intact.
        Middle messages are replaced with structural summaries."""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars <= self.max_context_chars:
            return

        # First 2 = system prompt + original user request; each turn = 2 msgs (assistant + user)
        protected_tail = keep_recent * 2
        if len(messages) <= 2 + protected_tail:
            return

        compactable_start = 2
        compactable_end = len(messages) - protected_tail

        for i in range(compactable_start, compactable_end):
            msg = messages[i]
            content = msg.get("content", "")
            if len(content) <= 300:
                continue

            if msg["role"] == "assistant":
                summary_parts = []
                for match in re.finditer(r'```action:write_file\n(.*?)```', content, re.DOTALL):
                    body = match.group(1)
                    path = ""
                    line_count = body.count("\n")
                    for line in body.split("\n")[:3]:
                        if line.startswith("path:"):
                            path = line.split(":", 1)[1].strip()
                            break
                    if path:
                        summary_parts.append("写入 {} ({}行)".format(path, line_count))
                for match in re.finditer(r'```action:run\n(.*?)```', content, re.DOTALL):
                    cmd = match.group(1).strip()[:80]
                    summary_parts.append("运行: {}".format(cmd))
                if summary_parts:
                    messages[i] = {"role": "assistant", "content": "[历史摘要: {}]".format("; ".join(summary_parts))}
                else:
                    messages[i] = {"role": "assistant", "content": content[:200] + "\n...(已压缩)"}
            elif msg["role"] == "user":
                messages[i] = {"role": "user", "content": content[:500] + ("\n...(已压缩)" if len(content) > 500 else "")}

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

    def _parse_actions(self, response: str) -> list[dict]:
        """解析代码块格式的action调用"""
        actions = []
        pattern = r'```action:(\w+)\n([\s\S]*?)```'
        for match in re.finditer(pattern, response):
            action_type = match.group(1)
            body = match.group(2).strip()
            actions.append({"type": action_type, "body": body})
        return actions

    @staticmethod
    def _extract_files_fallback(response: str) -> dict[str, str]:
        """Fallback extraction when model outputs code without action: prefix"""
        files = {}
        for match in re.finditer(r'```filepath:([^\n]+)\n([\s\S]*?)\n```', response):
            fp = match.group(1).strip()
            code = match.group(2)
            if code and len(code) > 20:
                files[fp] = code
        if files:
            return files
        for match in re.finditer(r'```(?:html|htm)\n([\s\S]*?)\n```', response, re.IGNORECASE):
            code = match.group(1).strip()
            if code and len(code) > 50 and ('<html' in code.lower() or '<!doctype' in code.lower()):
                files["index.html"] = code
                break
        if not files:
            # Match complete HTML
            html_match = re.search(r'(<!DOCTYPE[\s\S]*?</html>)', response, re.IGNORECASE)
            if html_match and len(html_match.group(1)) > 100:
                files["index.html"] = html_match.group(1)
        if not files:
            # Last resort: match truncated HTML (model hit token limit before closing </html>)
            html_match = re.search(r'(<!DOCTYPE[\s\S]{200,})', response, re.IGNORECASE)
            if html_match:
                code = html_match.group(1)
                if len(code) > 500:
                    files["index.html"] = code
        return files

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
                    except Exception as e:
                        log.debug("suppressed: %s", e)

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
