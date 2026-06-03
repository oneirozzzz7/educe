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
            "将以下编程任务分解为3-5个实现步骤。每步是一个可独立验证的功能单元。\n"
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
                code_section = "\n\n".join(
                    "```filepath:{}\n{}\n```".format(fp, code)
                    for fp, code in accumulated_files.items()
                )
                prompt = (
                    "实现步骤{}/{}: {}\n\n"
                    "原始需求: {}\n\n"
                    "当前已有代码:\n{}\n\n"
                    "在此基础上完成这一步。输出修改后的完整文件，用```filepath:格式。"
                ).format(i + 1, len(steps), step, original_request, code_section)
            else:
                prompt = (
                    "实现步骤{}/{}: {}\n\n"
                    "原始需求: {}\n\n"
                    "输出完整代码文件，用```filepath:文件名格式包裹。不要解释，直接输出代码。"
                ).format(i + 1, len(steps), step, original_request)

            response = await call_model_fn(prompt)
            new_files = self._extract_files(response)

            if not new_files:
                if on_progress:
                    on_progress("步骤{} 未产出代码，跳过".format(i + 1))
                continue

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
        for match in re.finditer(r'```filepath:([^\n]+)\n([\s\S]*?)```', content):
            files[match.group(1).strip()] = match.group(2)
        return files
