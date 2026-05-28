"""
Tester Agent — 全维度质量保障
不是重复Builder的语法检查，而是独立视角的功能/UI/安全/性能审视
"""
from __future__ import annotations

from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.core.tools import RunHTMLTool, RunPythonTool, ReadFileTool


class TesterAgent(BaseAgent):
    name = "tester"
    role = "Tester"
    description = "全维度质量保障：功能正确性/UI质量/边界情况/安全/性能"

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        code_files = context.artifacts.get("code_files", [])
        engineer_output = context.artifacts.get("engineer_output", "")
        user_request = context.user_request

        if not code_files and not engineer_output:
            yield self.emit("user", "无产出物可测试")
            return

        # 用工具做真实验证
        tool_results = await self._run_tool_checks(code_files)

        # 用LLM做全维度审视
        prompt = self._build_prompt(user_request, engineer_output, tool_results)
        messages = [{"role": "user", "content": prompt}]
        review = await self.call_model(messages, context)

        # 解析通过/不通过
        passed = self._parse_verdict(review)
        context.add_artifact("test_result", {"passed": passed, "report": review})

        yield self.emit("user", review)

    async def _run_tool_checks(self, code_files: list[str]) -> str:
        """用工具做真实检测"""
        results = []
        for filepath in code_files:
            if filepath.endswith(".html"):
                tool = RunHTMLTool()
                r = await tool.execute({"path": filepath})
                results.append(f"[HTML验证] {filepath}: {r}")
            elif filepath.endswith(".py"):
                tool = RunPythonTool()
                r = await tool.execute({"path": filepath})
                results.append(f"[Python运行] {filepath}: {r}")
        return "\n".join(results) if results else "无工具检测结果"

    def _build_prompt(self, user_request: str, code: str, tool_results: str) -> str:
        return f"""你是一个严格的全维度产品测试专家。

## 用户原始需求
{user_request}

## 工具验证结果（真实运行）
{tool_results}

## 代码内容
{code[:4000]}

## 你的测试维度（必须逐项检查）

### 1. 功能正确性
- 核心功能是否全部实现？
- 逻辑是否正确（计算、状态管理、事件处理）？

### 2. UI质量
- 有没有视觉层次（颜色、阴影、间距）？
- 交互有没有反馈（hover、click、loading状态）？
- 是否响应式？

### 3. 边界情况
- 空输入会崩吗？超大输入呢？
- 快速重复操作会出问题吗？

### 4. 安全性
- 有没有innerHTML直接插入用户输入（XSS风险）？
- 有没有eval()或其他危险函数？

### 5. 产品完整度
- 有没有空状态提示？
- 有没有操作成功/失败反馈？
- 用户能不能第一次使用就知道怎么用？

## 输出格式
给出每个维度的评分(1-5)和具体问题。最后判定：
- PASS：核心功能实现(功能正确性≥3)且代码能运行(工具验证通过)
- FAIL：核心功能未实现 或 代码无法运行 或 有P0安全漏洞

注意：UI不完美、缺少边界处理等不算FAIL，只算改进建议。
只有"核心功能缺失"或"代码不能跑"才FAIL。

最后一行必须是：VERDICT: PASS 或 VERDICT: FAIL"""

    def _parse_verdict(self, review: str) -> bool:
        if "VERDICT: PASS" in review:
            return True
        if "VERDICT: FAIL" in review:
            return False
        # 默认宽松通过（避免无限循环）
        return "严重" not in review and "P0" not in review
