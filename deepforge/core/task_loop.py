"""
TaskLoop — 跨轮次自主执行循环

模型自己决定：做完这轮后还要做什么？质量够不够？该停了吗？
上下文分层管理：每次调用只给模型当前需要的信息，不堆积历史。

用法：
    loop = TaskLoop(orchestrator)
    await loop.run("帮我做个MBTI测试，持续改进到满意", budget_minutes=30)
"""
from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepforge.core.orchestrator import Orchestrator


@dataclass
class LoopIteration:
    index: int
    action: str  # "improve" | "add_feature" | "fix_bug" | "test" | "stop"
    instruction: str
    elapsed: float = 0.0
    outcome: str = ""


@dataclass
class LoopResult:
    iterations: list[LoopIteration] = field(default_factory=list)
    total_elapsed: float = 0.0
    stop_reason: str = ""  # "quality_met" | "budget_exhausted" | "no_progress" | "model_decided"


ASSESS_SYSTEM = """你是一个产品质量评估器。根据当前产物的状态，决定下一步动作。

你会看到：
- 用户的原始需求
- 目前已完成的工作摘要
- 当前代码的关键信息

你的输出必须严格按格式：
ACTION: improve|add_feature|fix_bug|test|stop
INSTRUCTION: 一句话描述要做什么（如果ACTION是stop则写停止原因）
REASON: 为什么选这个动作

规则：
- 如果产物已经完整满足用户需求且质量良好 → stop
- 如果有明显缺陷（功能不完整/交互缺失/UI粗糙）→ improve 或 fix_bug
- 如果核心功能完成但可以增加亮点 → add_feature
- 如果改了多轮但质量没提升 → stop（避免打转）
- 每次INSTRUCTION必须具体，不能是"继续优化"这种空话"""


class TaskLoop:
    def __init__(self, orchestrator: "Orchestrator"):
        self.orch = orchestrator
        self.iterations: list[LoopIteration] = []
        self.max_stale_rounds = 2  # 连续无进展则停止

    async def run(
        self,
        user_goal: str,
        budget_minutes: float = 30,
        max_iterations: int = 10,
        on_progress: callable = None,
    ) -> LoopResult:
        """
        自主循环执行，直到模型认为完成或预算耗尽。

        user_goal: 用户的高层目标（可以模糊，如"持续改进"）
        budget_minutes: 时间预算
        max_iterations: 最大迭代次数兜底
        on_progress: 每轮回调 (iteration: LoopIteration) -> None (sync or async)
        """
        start_time = time.time()
        budget_seconds = budget_minutes * 60
        stale_count = 0
        result = LoopResult()

        async def _notify(it):
            if on_progress:
                r = on_progress(it)
                if asyncio.iscoroutine(r):
                    await r

        # 第一轮：执行原始需求（如果还没有产物）
        has_artifact = bool(self.orch.context.artifacts.get("engineer_output"))
        if not has_artifact:
            iter_start = time.time()
            await self.orch.run(user_goal)
            elapsed = time.time() - iter_start
            iteration = LoopIteration(
                index=0, action="build", instruction=user_goal,
                elapsed=elapsed, outcome=self._get_outcome_summary())
            self.iterations.append(iteration)
            await _notify(iteration)

        # 迭代循环
        for i in range(max_iterations):
            # 预算检查
            total_elapsed = time.time() - start_time
            if total_elapsed >= budget_seconds:
                result.stop_reason = "budget_exhausted"
                break

            remaining_minutes = (budget_seconds - total_elapsed) / 60

            # 评估：模型决定下一步
            action, instruction, reason = await self._assess(
                user_goal, remaining_minutes)

            if action == "stop":
                iteration = LoopIteration(
                    index=len(self.iterations), action="stop",
                    instruction=instruction)
                self.iterations.append(iteration)
                await _notify(iteration)
                result.stop_reason = "model_decided"
                break

            # 执行
            iter_start = time.time()
            build_instruction = self._build_iteration_instruction(
                action, instruction, user_goal)
            await self.orch.run(build_instruction)
            elapsed = time.time() - iter_start

            outcome = self._get_outcome_summary()
            iteration = LoopIteration(
                index=len(self.iterations), action=action,
                instruction=instruction, elapsed=elapsed, outcome=outcome)
            self.iterations.append(iteration)
            await _notify(iteration)

            # 检测停滞
            if self._is_stale(iteration):
                stale_count += 1
                if stale_count >= self.max_stale_rounds:
                    result.stop_reason = "no_progress"
                    break
            else:
                stale_count = 0

        if not result.stop_reason:
            result.stop_reason = "max_iterations"

        result.iterations = self.iterations
        result.total_elapsed = time.time() - start_time
        return result

    async def _assess(
        self, user_goal: str, remaining_minutes: float
    ) -> tuple[str, str, str]:
        """
        分层上下文组装 + 模型评估。
        只给模型当前需要的信息，不堆积全部历史。
        """
        client = self.orch._get_client()
        if not client:
            return ("stop", "无可用模型", "")

        # Layer 1: 当前任务
        task_ctx = "用户目标: {}\n剩余预算: {:.0f}分钟".format(
            user_goal[:200], remaining_minutes)

        # Layer 2: 位置感知（已完成的迭代摘要）
        history_ctx = ""
        if self.iterations:
            lines = []
            for it in self.iterations[-5:]:  # 只看最近5轮
                lines.append("  轮{}: [{}] {} → {}".format(
                    it.index, it.action, it.instruction[:60],
                    it.outcome[:60] if it.outcome else ""))
            history_ctx = "\n已完成的迭代:\n" + "\n".join(lines)

        # Layer 3: 工作区（当前产物状态）
        artifact_ctx = self._get_artifact_context()

        # 组装评估 prompt（总计约 2K tokens）
        user_msg = "{}\n{}\n\n当前产物状态:\n{}".format(
            task_ctx, history_ctx, artifact_ctx)

        try:
            response = await client.chat(
                messages=[
                    {"role": "system", "content": ASSESS_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                model=self.orch.config.default_model.model,
                max_tokens=200,
                temperature=0.0,
            )
            return self._parse_assessment(response)
        except Exception as e:
            return ("stop", "评估失败: {}".format(str(e)[:50]), "")

    def _parse_assessment(self, response: str) -> tuple[str, str, str]:
        """解析模型的评估输出"""
        import re
        action = "stop"
        instruction = ""
        reason = ""

        action_m = re.search(r'ACTION:\s*(\w+)', response)
        if action_m:
            raw_action = action_m.group(1).lower()
            if raw_action in ("improve", "add_feature", "fix_bug", "test", "stop"):
                action = raw_action

        instr_m = re.search(r'INSTRUCTION:\s*(.+)', response)
        if instr_m:
            instruction = instr_m.group(1).strip()

        reason_m = re.search(r'REASON:\s*(.+)', response)
        if reason_m:
            reason = reason_m.group(1).strip()

        return (action, instruction, reason)

    def _build_iteration_instruction(
        self, action: str, instruction: str, user_goal: str
    ) -> str:
        """把评估结果转化为 orchestrator 可执行的输入"""
        prefix_map = {
            "improve": "改进当前代码",
            "add_feature": "在现有代码基础上添加功能",
            "fix_bug": "修复代码中的问题",
            "test": "测试并修复发现的问题",
        }
        prefix = prefix_map.get(action, "修改")
        return "{}：{}\n\n原始需求：{}".format(prefix, instruction, user_goal[:200])

    def _get_artifact_context(self) -> str:
        """Layer 3: 当前产物的关键信息（不是全部代码）"""
        code_files = self.orch.context.artifacts.get("code_files", [])
        if not code_files:
            return "暂无产物"

        from pathlib import Path
        parts = []
        for fp in code_files[:3]:
            p = Path(fp)
            if p.exists():
                content = p.read_text(encoding="utf-8", errors="ignore")
                lines = content.count("\n")
                size = len(content)
                # 提取结构信息而非全部代码
                structure = self._extract_structure(content, p.suffix)
                parts.append("- {} ({} 行, {:.1f}KB)\n  结构: {}".format(
                    p.name, lines, size / 1024, structure))
            else:
                parts.append("- {} (文件不存在)".format(fp.split("/")[-1]))

        return "\n".join(parts)

    def _extract_structure(self, content: str, suffix: str) -> str:
        """从代码中提取结构摘要（函数名/组件/关键元素），不传全文"""
        import re
        if suffix == ".html":
            # 提取关键交互元素
            buttons = re.findall(r'<button[^>]*>([^<]*)</button>', content)
            inputs = re.findall(r'<input[^>]*type="([^"]*)"', content)
            scripts = content.count("<script")
            has_canvas = "canvas" in content.lower()
            has_animation = "animation" in content or "@keyframes" in content
            parts = []
            if buttons:
                parts.append("按钮: {}".format(", ".join(buttons[:5])))
            if inputs:
                parts.append("输入: {}".format(", ".join(inputs[:3])))
            if scripts:
                parts.append("{}个<script>块".format(scripts))
            if has_canvas:
                parts.append("有Canvas")
            if has_animation:
                parts.append("有动画")
            return "; ".join(parts) if parts else "纯静态HTML"

        elif suffix == ".py":
            funcs = re.findall(r'def (\w+)\(', content)
            classes = re.findall(r'class (\w+)', content)
            parts = []
            if classes:
                parts.append("类: {}".format(", ".join(classes[:5])))
            if funcs:
                parts.append("函数: {}".format(", ".join(funcs[:8])))
            return "; ".join(parts) if parts else "脚本"

        elif suffix == ".js":
            funcs = re.findall(r'function (\w+)', content)
            classes = re.findall(r'class (\w+)', content)
            parts = []
            if classes:
                parts.append("类: {}".format(", ".join(classes[:5])))
            if funcs:
                parts.append("函数: {}".format(", ".join(funcs[:8])))
            return "; ".join(parts) if parts else "脚本"

        return "未知类型"

    def _get_outcome_summary(self) -> str:
        """从 orchestrator 状态提取本轮结果摘要"""
        code_files = self.orch.context.artifacts.get("code_files", [])
        if code_files:
            from pathlib import Path
            names = [Path(f).name for f in code_files[:3]]
            return "产出: {}".format(", ".join(names))
        return "未产出文件"

    def _is_stale(self, iteration: LoopIteration) -> bool:
        """检测这轮是否没有实质进展"""
        if not iteration.outcome or "未产出" in iteration.outcome:
            return True
        # 如果连续两轮 action+instruction 几乎一样，也算停滞
        if len(self.iterations) >= 2:
            prev = self.iterations[-2]
            if prev.action == iteration.action and prev.instruction == iteration.instruction:
                return True
        return False
