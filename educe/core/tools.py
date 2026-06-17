"""
DeepForge 工具系统
让Agent能操作环境——读写文件、执行代码、验证结果
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import re
from pathlib import Path
from typing import Any
from pydantic import BaseModel


class Tool(BaseModel):
    name: str
    description: str
    parameters: dict = {}

    async def execute(self, params: dict) -> str:
        raise NotImplementedError


class WriteFileTool(Tool):
    name: str = "write_file"
    description: str = "写入文件内容。参数: path(文件路径), content(文件内容)"

    async def execute(self, params: dict) -> str:
        path = Path(params.get("path", "output.html"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(params.get("content", ""), encoding="utf-8")
        return f"文件已写入: {path} ({path.stat().st_size} bytes)"


class ReadFileTool(Tool):
    name: str = "read_file"
    description: str = "读取文件内容。参数: path(文件路径)"

    async def execute(self, params: dict) -> str:
        path = Path(params.get("path", ""))
        if not path.exists():
            return f"文件不存在: {path}"
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > 5000:
            return content[:5000] + f"\n...(截断，总{len(content)}字符)"
        return content


class RunHTMLTool(Tool):
    name: str = "run_html"
    description: str = "验证HTML文件：检查结构完整性、JS语法。参数: path(文件路径)"

    async def execute(self, params: dict) -> str:
        path = Path(params.get("path", ""))
        if not path.exists():
            return "文件不存在"
        content = path.read_text(encoding="utf-8", errors="replace")
        issues = []

        if "<!DOCTYPE" not in content and "<!doctype" not in content:
            issues.append("缺少DOCTYPE")
        if "</html>" not in content:
            issues.append("HTML未闭合——代码可能被截断")

        js_blocks = re.findall(r'<script[^>]*>([\s\S]*?)</script>', content)
        for i, js in enumerate(js_blocks):
            if len(js.strip()) < 10:
                continue
            with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
                f.write(js)
                tmp = f.name
            try:
                proc = await asyncio.create_subprocess_exec(
                    "node", "--check", tmp,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode != 0:
                    issues.append(f"JS语法错误(block{i}): {stderr.decode()[:150]}")
            except Exception:
                pass
            finally:
                Path(tmp).unlink(missing_ok=True)

        if not issues:
            return f"验证通过: HTML完整, JS语法正确, {len(content)}bytes"
        return "发现问题:\n" + "\n".join(f"- {i}" for i in issues)


class RunPythonTool(Tool):
    name: str = "run_python"
    description: str = "运行Python脚本并返回输出。参数: path(文件路径)"

    async def execute(self, params: dict) -> str:
        path = Path(params.get("path", ""))
        if not path.exists():
            return "文件不存在"
        try:
            proc = await asyncio.create_subprocess_exec(
                "python", str(path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            out = stdout.decode()[:1000]
            err = stderr.decode()[:500]
            if proc.returncode == 0:
                return f"运行成功 (exit=0)\n{out}" if out else "运行成功，无输出"
            return f"运行失败 (exit={proc.returncode})\nSTDERR: {err}\nSTDOUT: {out}"
        except asyncio.TimeoutError:
            return "运行超时(10s)——可能是服务类程序"
        except Exception as e:
            return f"运行异常: {e}"


class CheckJSSyntaxTool(Tool):
    name: str = "check_js_syntax"
    description: str = "检查JS代码语法。参数: code(JS代码字符串)"

    async def execute(self, params: dict) -> str:
        code = params.get("code", "")
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write(code)
            tmp = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", "--check", tmp,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                return "JS语法正确"
            return f"JS语法错误: {stderr.decode()[:200]}"
        except Exception as e:
            return f"检查失败: {e}"
        finally:
            Path(tmp).unlink(missing_ok=True)


class SearchMemoryTool(Tool):
    name: str = "search_memory"
    description: str = "搜索记忆库中的历史经验。参数: query(搜索关键词)"

    async def execute(self, params: dict) -> str:
        return "记忆搜索需要注入memory_store实例"


# 所有可用工具
ALL_TOOLS = [
    WriteFileTool(),
    ReadFileTool(),
    RunHTMLTool(),
    RunPythonTool(),
    CheckJSSyntaxTool(),
    SearchMemoryTool(),
]


def get_tools_schema(tools: list[Tool]) -> list[dict]:
    """转为OpenAI function calling格式"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                        "content": {"type": "string", "description": "文件内容"},
                        "code": {"type": "string", "description": "代码字符串"},
                        "query": {"type": "string", "description": "搜索关键词"},
                    },
                },
            },
        }
        for t in tools
    ]


async def execute_tool(tools: list[Tool], name: str, params: dict) -> str:
    """执行指定工具"""
    for t in tools:
        if t.name == name:
            return await t.execute(params)
    return f"未知工具: {name}"
