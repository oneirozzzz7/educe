"""
成功轨迹自动编译器 — Verify-Compile Loop 核心

当一个多步任务成功完成时：
1. 收集执行轨迹（action序列 + 验证结果）
2. 抽象参数化（识别哪些是变量）
3. 编译为 CompositeSkill L0（文本描述+步骤序列）
4. 注册到 SkillRegistry

触发条件：3+ 步 action 全部成功 + 无 nudge 收敛 = "干净的成功轨迹"
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("educe.trace_compiler")


@dataclass
class TraceStep:
    """单步执行记录"""
    action_type: str
    params: str
    output: str = ""
    success: bool = False
    elapsed_ms: int = 0


@dataclass
class ExecutionTrace:
    """完整执行轨迹"""
    user_input: str
    steps: list[TraceStep] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed: bool = False
    had_failures: bool = False
    had_nudge: bool = False

    def add_step(self, action_type: str, params: str, output: str,
                 success: bool, elapsed_ms: int = 0):
        self.steps.append(TraceStep(
            action_type=action_type, params=params,
            output=output[:500], success=success, elapsed_ms=elapsed_ms,
        ))
        if not success:
            self.had_failures = True

    def is_compilable(self) -> bool:
        """判断该轨迹是否值得编译为 skill"""
        if len(self.steps) < 2:
            return False
        if self.had_nudge:
            return False
        all_success = all(s.success for s in self.steps)
        if not all_success and not self._recovered_from_failure():
            return False
        return True

    def _recovered_from_failure(self) -> bool:
        """是否经历了失败→修复→成功的恢复过程"""
        if not self.had_failures:
            return True
        last_steps = self.steps[-3:] if len(self.steps) >= 3 else self.steps
        return last_steps[-1].success if last_steps else False

    def compile_to_skill_dict(self) -> dict | None:
        """将轨迹编译为 skill 字典（可直接注册到 SkillRegistry）"""
        if not self.is_compilable():
            return None

        successful_steps = [s for s in self.steps if s.success]
        if len(successful_steps) < 2:
            return None

        skill_id = f"trace_{hashlib.md5(self.user_input.encode()).hexdigest()[:8]}"
        keywords = self._extract_keywords()

        steps_dicts = []
        for i, step in enumerate(successful_steps):
            steps_dicts.append({
                "idx": i,
                "action_type": step.action_type,
                "template": step.params[:200],
                "verify": "exit_code == 0" if step.action_type == "shell" else "success",
            })

        hint = self._generate_hint(successful_steps)

        return {
            "skill_id": skill_id,
            "name": f"auto:{self.user_input[:30]}",
            "version": 1,
            "level": 0,
            "scope": self._detect_scope(),
            "safety_class": "reversible",
            "hint_text": hint,
            "steps": steps_dicts,
            "graph_edges": [],
            "guards": [],
            "trigger_scope": [self._detect_scope()],
            "trigger_keywords": keywords,
            "position_hint": "anywhere",
            "stats": {"invocations": 1, "successes": 1},
            "approved_max_level": 1,
            "frozen": False,
            "created_at": time.time(),
            "confidence": 0.5,
            "support": 1,
        }

    def _extract_keywords(self) -> list[str]:
        """从用户输入中提取关键词作为触发条件"""
        import re
        words = re.findall(r'[\w]+', self.user_input)
        stop_words = {"帮我", "请", "写", "一个", "的", "和", "然后", "执行", "运行",
                      "创建", "修改", "the", "a", "an", "to", "and", "or"}
        keywords = [w for w in words if len(w) > 1 and w.lower() not in stop_words]
        return keywords[:5]

    def _detect_scope(self) -> str:
        """检测任务域"""
        action_types = {s.action_type for s in self.steps}
        if "shell" in action_types and "write_file" in action_types:
            return "CODE"
        if "shell" in action_types:
            return "TECH"
        return "GENERAL"

    def _generate_hint(self, steps: list[TraceStep]) -> str:
        """生成 L0 文本描述"""
        parts = []
        for s in steps[:5]:
            if s.action_type == "shell":
                parts.append(f"执行: {s.params[:60]}")
            elif s.action_type == "write_file":
                parts.append(f"写入文件")
            elif s.action_type == "edit_file":
                parts.append(f"编辑文件")
            else:
                parts.append(f"{s.action_type}")
        return " → ".join(parts)


class TraceCollector:
    """轨迹收集器 — 在 action_loop 中使用"""

    def __init__(self):
        self._current: ExecutionTrace | None = None

    def start(self, user_input: str):
        self._current = ExecutionTrace(user_input=user_input)

    def record(self, action_type: str, params: str, output: str,
               success: bool, elapsed_ms: int = 0):
        if self._current:
            self._current.add_step(action_type, params, output, success, elapsed_ms)

    def mark_nudge(self):
        if self._current:
            self._current.had_nudge = True

    def finish(self) -> dict | None:
        """完成收集并尝试编译。返回 skill_dict 或 None"""
        if not self._current:
            return None
        self._current.completed = True
        result = self._current.compile_to_skill_dict()
        self._current = None
        if result:
            log.info("TraceCompiler: compiled skill '%s' (%d steps)",
                     result["name"], len(result["steps"]))
        return result
