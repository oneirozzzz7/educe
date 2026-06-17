from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any


class ToolBox:
    @staticmethod
    async def read_file(path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"[ERROR] 文件不存在: {path}"
        return p.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    async def write_file(path: str, content: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[OK] 文件已写入: {path}"

    @staticmethod
    async def list_dir(path: str = ".") -> str:
        p = Path(path)
        if not p.exists():
            return f"[ERROR] 目录不存在: {path}"
        items = []
        for item in sorted(p.iterdir()):
            prefix = "📁" if item.is_dir() else "📄"
            items.append(f"{prefix} {item.name}")
        return "\n".join(items) if items else "(空目录)"

    @staticmethod
    async def run_command(command: str, cwd: str = ".", timeout: int = 60) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")
            result = ""
            if output:
                result += output
            if errors:
                result += f"\n[STDERR]\n{errors}"
            result += f"\n[EXIT CODE: {proc.returncode}]"
            return result
        except asyncio.TimeoutError:
            return f"[ERROR] 命令超时 ({timeout}s): {command}"
        except Exception as e:
            return f"[ERROR] 执行失败: {e}"

    @staticmethod
    async def search_files(pattern: str, path: str = ".", max_results: int = 50) -> str:
        p = Path(path)
        if not p.exists():
            return f"[ERROR] 路径不存在: {path}"
        results = []
        for match in p.rglob(pattern):
            if any(part.startswith(".") for part in match.parts):
                continue
            if "node_modules" in match.parts or "__pycache__" in match.parts:
                continue
            results.append(str(match))
            if len(results) >= max_results:
                break
        return "\n".join(results) if results else f"未找到匹配: {pattern}"

    @staticmethod
    async def grep(pattern: str, path: str = ".", file_pattern: str = "*") -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "grep", "-rn", "--include", file_pattern, pattern, path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace")
            lines = output.strip().split("\n")
            if len(lines) > 50:
                lines = lines[:50] + [f"... (共 {len(lines)} 条结果)"]
            return "\n".join(lines) if lines[0] else f"未找到匹配: {pattern}"
        except Exception as e:
            return f"[ERROR] 搜索失败: {e}"

    @classmethod
    def get_tool_descriptions(cls) -> list[dict[str, str]]:
        return [
            {"name": "read_file", "description": "读取文件内容", "params": "path: str"},
            {"name": "write_file", "description": "写入文件内容", "params": "path: str, content: str"},
            {"name": "list_dir", "description": "列出目录内容", "params": "path: str"},
            {"name": "run_command", "description": "执行shell命令", "params": "command: str, cwd: str"},
            {"name": "search_files", "description": "搜索文件", "params": "pattern: str, path: str"},
            {"name": "grep", "description": "在文件中搜索文本", "params": "pattern: str, path: str"},
        ]
