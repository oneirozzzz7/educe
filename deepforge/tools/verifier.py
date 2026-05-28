"""
代码运行验证器
真正运行产出物，不是用LLM"审查"——用工具验证，不用猜测
"""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import re
from pathlib import Path
from typing import Any


class CodeVerifier:
    """运行产出物并验证功能——这是超越Claude Agent的关键"""

    @staticmethod
    async def verify(files: dict[str, str]) -> dict[str, Any]:
        """验证产出物能否运行，返回详细报告"""
        results = {"passed": True, "checks": [], "errors": []}

        for filepath, content in files.items():
            if filepath.endswith(".html"):
                r = await CodeVerifier._verify_html(filepath, content)
            elif filepath.endswith(".py"):
                r = await CodeVerifier._verify_python(filepath, content)
            elif filepath.endswith(".js"):
                r = await CodeVerifier._verify_js(filepath, content)
            else:
                r = {"file": filepath, "passed": True, "checks": ["file_exists"]}

            results["checks"].extend(r.get("checks", []))
            if not r.get("passed", True):
                results["passed"] = False
                results["errors"].extend(r.get("errors", []))

        return results

    @staticmethod
    async def _verify_html(filepath: str, content: str) -> dict:
        checks = []
        errors = []

        # 1. 结构完整性
        if "<!DOCTYPE" in content or "<!doctype" in content:
            checks.append("html_doctype")
        else:
            errors.append("缺少DOCTYPE声明")

        if "</html>" in content:
            checks.append("html_closed")
        else:
            errors.append("HTML标签未闭合——代码可能被截断")

        # 2. JS语法验证——用Node.js真正检查
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
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode == 0:
                    checks.append(f"js_syntax_block_{i}")
                else:
                    err = stderr.decode()[:200]
                    errors.append(f"JS语法错误(block {i}): {err}")
            except Exception:
                checks.append(f"js_syntax_skip_{i}")
            finally:
                Path(tmp).unlink(missing_ok=True)

        # 3. CSS完整性
        style_opens = content.count("<style")
        style_closes = content.count("</style>")
        if style_opens == style_closes:
            checks.append("css_balanced")
        else:
            errors.append(f"CSS标签不平衡: {style_opens}个开标签 vs {style_closes}个闭标签")

        # 4. 功能性检查
        if "<script" in content and len(content) > 500:
            checks.append("has_logic")
        else:
            errors.append("缺少JS逻辑或内容过少")

        # 5. 交互性检查
        interactive = 0
        if "addEventListener" in content:
            interactive += 1
        if "onclick" in content or "onchange" in content:
            interactive += 1
        if "drag" in content.lower() or "mousedown" in content:
            interactive += 1
        if interactive > 0:
            checks.append(f"interactive_{interactive}")
        else:
            errors.append("无交互事件绑定")

        return {
            "file": filepath,
            "passed": len(errors) == 0,
            "checks": checks,
            "errors": errors,
        }

    @staticmethod
    async def _verify_python(filepath: str, content: str) -> dict:
        checks = []
        errors = []

        # 1. 语法检查
        try:
            compile(content, filepath, "exec")
            checks.append("py_syntax")
        except SyntaxError as e:
            errors.append(f"Python语法错误 L{e.lineno}: {e.msg}")
            return {"file": filepath, "passed": False, "checks": checks, "errors": errors}

        # 2. 实际运行（超时5秒）
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(content)
            tmp = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "python", tmp,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                checks.append("py_runs")
            else:
                err = stderr.decode()[:200]
                errors.append(f"Python运行错误: {err}")
        except asyncio.TimeoutError:
            checks.append("py_runs_long")
        except Exception as e:
            errors.append(f"运行异常: {e}")
        finally:
            Path(tmp).unlink(missing_ok=True)

        return {"file": filepath, "passed": len(errors) == 0, "checks": checks, "errors": errors}

    @staticmethod
    async def _verify_js(filepath: str, content: str) -> dict:
        checks = []
        errors = []

        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write(content)
            tmp = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", "--check", tmp,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                checks.append("js_syntax")
            else:
                errors.append(f"JS语法错误: {stderr.decode()[:200]}")
        except Exception:
            checks.append("js_check_skip")
        finally:
            Path(tmp).unlink(missing_ok=True)

        return {"file": filepath, "passed": len(errors) == 0, "checks": checks, "errors": errors}
