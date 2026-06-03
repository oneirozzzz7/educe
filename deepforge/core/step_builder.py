"""
增量步骤构建器
对复杂任务：分步生成，每步验证，逐步累积。
每步~6K tokens，弱模型轻松胜任。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Awaitable

from deepforge.core.execution_loop import ExecutionLoop


class StepBuilder:
    def __init__(self, max_steps: int = 5, max_fix_per_step: int = 3):
        self.max_steps = max_steps
        self.loop = ExecutionLoop(max_rounds=max_fix_per_step)

    async def plan_steps(
        self,
        user_request: str,
        call_model_fn: Callable[[str], Awaitable[str]],
    ) -> list[str]:
        prompt = (
            "将以下编程任务分解为3-5个实现步骤。\n\n"
            "关键要求：\n"
            "- 每步必须是一个用户可感知的功能点，不是技术架构步骤\n"
            "- 每步完成后程序都能运行，用户能看到新增功能\n"
            "- 步骤按功能优先级排列：先核心交互，再视觉效果，最后附加功能\n"
            "- 不要拆出初始化项目、搭建框架这类无直接产出的步骤\n\n"
            "只输出步骤列表，每行一个，格式：1. 描述\n\n"
            "任务：{}".format(user_request)
        )
        response = await call_model_fn(prompt)
        steps = []
        for line in response.strip().split("\n"):
            line = re.sub(r'^\d+[\.\)]\s*', '', line.strip())
            if line and len(line) > 5:
                steps.append(line)
        return steps[:self.max_steps] if steps else [user_request]

    async def build_incremental(
        self,
        steps: list[str],
        call_model_fn: Callable[[str], Awaitable[str]],
        output_dir: Path,
        original_request: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        accumulated_files: dict[str, str] = {}

        for i, step in enumerate(steps):
            if on_progress:
                on_progress("步骤{}/{}: {}".format(i + 1, len(steps), step[:30]))

            if accumulated_files:
                # Use the existing filename for consistency
                main_file = list(accumulated_files.keys())[0]
                code_section = "\n\n".join(
                    "```filepath:{}\n{}\n```".format(fp, code)
                    for fp, code in accumulated_files.items()
                )
                prompt = (
                    "实现步骤{}/{}: {}\n\n"
                    "原始需求: {}\n\n"
                    "当前已有代码:\n{}\n\n"
                    "在此基础上完成这一步。输出修改后的完整文件，格式如下：\n"
                    "```filepath:{}\n完整代码\n```"
                ).format(i + 1, len(steps), step, original_request, code_section, main_file)
            else:
                prompt = (
                    "实现步骤{}/{}: {}\n\n"
                    "原始需求: {}\n\n"
                    "直接输出完整代码文件，格式必须如下：\n"
                    "```filepath:文件名.html\n完整代码\n```\n\n"
                    "不要解释，直接输出代码。"
                ).format(i + 1, len(steps), step, original_request)

            response = await call_model_fn(prompt)
            new_files = self._extract_files(response)

            # Retry once with explicit format reminder if extraction failed
            if not new_files:
                retry_prompt = (
                    "你的输出格式不正确，我无法提取代码。请重新输出，"
                    "严格使用以下格式（注意是filepath:不是html）：\n\n"
                    "```filepath:game.html\n你的完整HTML代码\n```\n\n"
                    "原始要求：{}\n步骤：{}"
                ).format(original_request, step)
                response = await call_model_fn(retry_prompt)
                new_files = self._extract_files(response)

            if not new_files:
                if on_progress:
                    on_progress("步骤{} 未产出代码，跳过".format(i + 1))
                continue

            # Unify filename: if accumulated already has a main file, map new output to same name
            if accumulated_files and len(new_files) == 1:
                existing_main = list(accumulated_files.keys())[0]
                new_name = list(new_files.keys())[0]
                if new_name != existing_main:
                    new_files = {existing_main: list(new_files.values())[0]}

            accumulated_files.update(new_files)

            final_files, result = await self.loop.run(
                dict(accumulated_files),
                output_dir,
                call_model_fn,
                on_progress=on_progress,
            )
            accumulated_files.update(final_files)

            if on_progress:
                status = "✓" if result.passed else "⚠ {}个错误未解决".format(len(result.errors))
                on_progress("步骤{} {}".format(i + 1, status))

        return accumulated_files

    @staticmethod
    def _extract_files(content: str) -> dict[str, str]:
        files = {}
        # Format 1: ```filepath:filename\n...\n```
        for match in re.finditer(r'```filepath:([^\n]+)\n([\s\S]*?)```', content):
            files[match.group(1).strip()] = match.group(2)
        if files:
            return files

        # Format 2: ```html\n...\n``` or ```python\n...\n``` etc
        lang_to_ext = {"html": ".html", "python": ".py", "javascript": ".js", "js": ".js", "css": ".css"}
        for match in re.finditer(r'```(\w+)\n([\s\S]*?)```', content):
            lang = match.group(1).lower()
            code = match.group(2)
            if lang in lang_to_ext and len(code.strip()) > 50:
                name = "index" + lang_to_ext[lang] if lang == "html" else "main" + lang_to_ext.get(lang, ".txt")
                files[name] = code
        if files:
            return files

        # Format 3: raw HTML without code fence
        if "<!DOCTYPE" in content or "<html" in content:
            html_match = re.search(r'(<!DOCTYPE[\s\S]*</html>)', content, re.IGNORECASE)
            if html_match:
                files["index.html"] = html_match.group(1)

        return files
