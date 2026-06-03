"""
框架驱动的执行反馈循环
核心思想：不等模型调工具——框架每次提取代码后自动运行验证，有错就喂回去让模型修。
"""
from __future__ import annotations

import re
import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable


@dataclass
class StructuredError:
    file: str
    line: int | None
    error_type: str
    message: str
    context_lines: str = ""


@dataclass
class VerifyResult:
    passed: bool
    errors: list[StructuredError] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


class ExecutionLoop:
    def __init__(self, max_rounds: int = 5):
        self.max_rounds = max_rounds
        self.rounds_used = 0

    async def run(
        self,
        files: dict[str, str],
        output_dir: Path,
        call_model_fn: Callable[[str], Awaitable[str]],
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, str], VerifyResult]:
        result = VerifyResult(passed=True)

        for round_num in range(self.max_rounds):
            self.rounds_used = round_num + 1
            result = await self.verify_files(files, output_dir)

            if result.passed:
                if on_progress:
                    on_progress("验证通过 ✓")
                break

            if on_progress:
                on_progress("发现{}个错误，修复中({}/{})...".format(
                    len(result.errors), round_num + 1, self.max_rounds))

            fix_prompt = self.build_fix_prompt(files, result)
            response = await call_model_fn(fix_prompt)
            new_files = self._extract_files(response)

            if not new_files:
                break

            files.update(new_files)

        return files, result

    async def verify_files(self, files: dict[str, str], output_dir: Path) -> VerifyResult:
        errors: list[StructuredError] = []
        stdout_all = ""
        stderr_all = ""

        for filepath, content in files.items():
            full_path = output_dir / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

            if filepath.endswith(".html"):
                html_errors = await self._verify_html(filepath, content, full_path)
                errors.extend(html_errors)
            elif filepath.endswith(".py"):
                py_errors, stdout, stderr = await self._verify_python(filepath, content, full_path)
                errors.extend(py_errors)
                stdout_all += stdout
                stderr_all += stderr
            elif filepath.endswith(".js"):
                js_errors = await self._verify_js(filepath, content, full_path)
                errors.extend(js_errors)

        return VerifyResult(
            passed=len(errors) == 0,
            errors=errors,
            stdout=stdout_all[:2000],
            stderr=stderr_all[:2000],
        )

    def build_fix_prompt(self, files: dict[str, str], result: VerifyResult) -> str:
        sections = []
        for i, err in enumerate(result.errors[:3]):
            ctx = err.context_lines or ""
            loc = "第{}行".format(err.line) if err.line else ""
            sections.append(
                "错误{}: {} {} — {}\n  {}\n{}".format(
                    i + 1, err.file, loc, err.error_type,
                    err.message,
                    "  上下文:\n{}".format(ctx) if ctx else "",
                )
            )

        prompt = "代码有{}个错误需要修复：\n\n{}\n\n请修复后输出完整文件，用```filepath:文件名格式包裹。".format(
            len(result.errors), "\n\n".join(sections))

        if result.stderr:
            prompt += "\n\n运行时错误:\n```\n{}\n```".format(result.stderr[:500])

        return prompt

    async def _verify_html(self, filepath: str, content: str, full_path: Path) -> list[StructuredError]:
        errors = []

        if "<!DOCTYPE" not in content and "<!doctype" not in content:
            errors.append(StructuredError(
                file=filepath, line=None, error_type="structure",
                message="缺少DOCTYPE声明"))

        if "</html>" not in content:
            errors.append(StructuredError(
                file=filepath, line=None, error_type="structure",
                message="HTML标签未闭合（缺少</html>）——代码可能被截断"))

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
                if proc.returncode != 0:
                    err_text = stderr.decode(errors="replace")
                    line_num = self._parse_node_error_line(err_text)
                    js_start = self._find_script_start_line(content, i)
                    abs_line = (js_start + line_num) if js_start and line_num else None
                    ctx = self._get_context(content, abs_line) if abs_line else ""
                    errors.append(StructuredError(
                        file=filepath, line=abs_line,
                        error_type="syntax",
                        message=err_text.strip()[:200],
                        context_lines=ctx))
            except (asyncio.TimeoutError, FileNotFoundError):
                pass
            finally:
                Path(tmp).unlink(missing_ok=True)

        # Headless smoke test — catch runtime errors, crash, blank page
        if not errors and "</html>" in content:
            runtime_errors = await self._smoke_test_html(full_path)
            errors.extend(runtime_errors)

        return errors

    async def _smoke_test_html(self, html_path: Path) -> list[StructuredError]:
        """Open HTML in headless browser, collect console errors and check for blank page."""
        errors: list[StructuredError] = []
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return errors

        server_proc = None
        port = 18921
        serve_dir = str(html_path.parent)
        try:
            server_proc = await asyncio.create_subprocess_exec(
                "python", "-m", "http.server", str(port), "--directory", serve_dir,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.sleep(0.3)

            url = f"http://localhost:{port}/{html_path.name}"
            console_errors: list[str] = []

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on("pageerror", lambda err: console_errors.append(str(err)))

                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=8000)
                    if resp and resp.status >= 400:
                        errors.append(StructuredError(
                            file=html_path.name, line=None, error_type="runtime",
                            message=f"页面加载失败 HTTP {resp.status}"))
                except Exception as e:
                    errors.append(StructuredError(
                        file=html_path.name, line=None, error_type="runtime",
                        message=f"页面打开超时或崩溃: {str(e)[:150]}"))
                    await browser.close()
                    return errors

                await asyncio.sleep(0.5)

                # Check for visible content (not blank)
                body_text = await page.evaluate("document.body?.innerText?.trim()?.length || 0")
                has_canvas = await page.evaluate("document.querySelectorAll('canvas').length > 0")
                has_svg = await page.evaluate("document.querySelectorAll('svg').length > 0")
                if body_text == 0 and not has_canvas and not has_svg:
                    errors.append(StructuredError(
                        file=html_path.name, line=None, error_type="runtime",
                        message="页面空白——没有可见文本、canvas或SVG元素"))

                if console_errors:
                    # Filter noise (e.g. favicon 404)
                    real_errors = [e for e in console_errors if "favicon" not in e.lower()]
                    if real_errors:
                        errors.append(StructuredError(
                            file=html_path.name, line=None, error_type="runtime",
                            message="JS运行时错误: " + "; ".join(real_errors[:3])[:300]))

                await browser.close()
        except Exception:
            pass
        finally:
            if server_proc:
                server_proc.terminate()
                await server_proc.wait()
        return errors

    async def _verify_python(self, filepath: str, content: str, full_path: Path) -> tuple[list[StructuredError], str, str]:
        errors = []

        try:
            compile(content, filepath, "exec")
        except SyntaxError as e:
            ctx = self._get_context(content, e.lineno)
            errors.append(StructuredError(
                file=filepath, line=e.lineno,
                error_type="syntax",
                message=str(e.msg),
                context_lines=ctx))
            return errors, "", ""

        try:
            proc = await asyncio.create_subprocess_exec(
                "python", str(full_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=10)
            stdout = stdout_b.decode(errors="replace")[:1000]
            stderr = stderr_b.decode(errors="replace")[:1000]

            if proc.returncode != 0:
                # 环境错误（缺包等）不算代码bug
                if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
                    return errors, stdout, ""
                line_num = self._parse_python_traceback_line(stderr)
                ctx = self._get_context(content, line_num) if line_num else ""
                errors.append(StructuredError(
                    file=filepath, line=line_num,
                    error_type="runtime",
                    message=stderr.strip()[-300:],
                    context_lines=ctx))
            return errors, stdout, stderr
        except asyncio.TimeoutError:
            return errors, "", "执行超时(>10s)"
        except FileNotFoundError:
            return errors, "", ""

    async def _verify_js(self, filepath: str, content: str, full_path: Path) -> list[StructuredError]:
        errors = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", "--check", str(full_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                err_text = stderr.decode(errors="replace")
                line_num = self._parse_node_error_line(err_text)
                ctx = self._get_context(content, line_num) if line_num else ""
                errors.append(StructuredError(
                    file=filepath, line=line_num,
                    error_type="syntax",
                    message=err_text.strip()[:200],
                    context_lines=ctx))
        except (asyncio.TimeoutError, FileNotFoundError):
            pass
        return errors

    def _get_context(self, content: str, line: int | None, radius: int = 3) -> str:
        if not line:
            return ""
        lines = content.split("\n")
        start = max(0, line - radius - 1)
        end = min(len(lines), line + radius)
        result = []
        for i in range(start, end):
            marker = " → " if i == line - 1 else "   "
            result.append("{}{:>4} | {}".format(marker, i + 1, lines[i]))
        return "\n".join(result)

    @staticmethod
    def _parse_node_error_line(stderr: str) -> int | None:
        m = re.search(r':(\d+)\b', stderr)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_python_traceback_line(stderr: str) -> int | None:
        matches = re.findall(r'line (\d+)', stderr)
        return int(matches[-1]) if matches else None

    @staticmethod
    def _find_script_start_line(html: str, block_index: int) -> int | None:
        count = 0
        for i, line in enumerate(html.split("\n"), 1):
            if "<script" in line.lower():
                if count == block_index:
                    return i
                count += 1
        return None

    @staticmethod
    def _extract_files(content: str) -> dict[str, str]:
        files = {}
        # Format 1: ```filepath:filename
        for match in re.finditer(r'```filepath:([^\n]+)\n([\s\S]*?)```', content):
            files[match.group(1).strip()] = match.group(2)
        if files:
            return files

        # Format 2: ```html / ```python / ```js etc
        lang_to_ext = {"html": ".html", "python": ".py", "javascript": ".js", "js": ".js", "css": ".css"}
        for match in re.finditer(r'```(\w+)\n([\s\S]*?)```', content):
            lang = match.group(1).lower()
            code = match.group(2)
            if lang in lang_to_ext and len(code.strip()) > 50:
                name = "index" + lang_to_ext[lang] if lang == "html" else "main" + lang_to_ext.get(lang, ".txt")
                files[name] = code
        if files:
            return files

        # Format 3: raw HTML
        if "<!DOCTYPE" in content or "<html" in content:
            html_match = re.search(r'(<!DOCTYPE[\s\S]*</html>)', content, re.IGNORECASE)
            if html_match:
                files["index.html"] = html_match.group(1)

        return files
