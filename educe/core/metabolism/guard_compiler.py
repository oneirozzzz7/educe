"""
GuardCompiler — 从因果路径自动推导 Guard 条件

阶段3核心组件。分析 skill 的执行历史，推导出形式化的守卫表达式。
守卫通过 = 可以安全地绕过 LLM 执行。

推导策略：
- readonly skill → 守卫宽松（prev_success + scope_match 即可）
- reversible skill → 守卫严格（file_exists + param_check + prev_success）
- destructive skill → 不编译守卫（永远不升 L3）
"""
from __future__ import annotations

from educe.core.metabolism.composite_skill import (
    CompositeSkill, Guard, SkillRegistry, SAFETY_CLASSES, MAX_LEVEL_BY_SAFETY,
)


class GuardCompiler:
    """从 skill 的执行历史和结构推导 Guard 条件"""

    def compile(self, skill: CompositeSkill) -> list[Guard]:
        """为 skill 编译守卫条件。返回空列表 = 不可升级到 L3。"""
        max_level = MAX_LEVEL_BY_SAFETY.get(skill.safety_class, 1)
        if max_level < 3:
            return []

        guards = []

        # 基础守卫：上次执行必须成功（防止连续失败循环）
        guards.append(Guard(
            kind="prev_success",
            expr="last_failure_age > 300",
            on_fail="escalate",
        ))

        # 按 safety_class 分策略
        if skill.safety_class == "readonly":
            guards.extend(self._compile_readonly_guards(skill))
        elif skill.safety_class == "idempotent":
            guards.extend(self._compile_idempotent_guards(skill))
        elif skill.safety_class == "reversible":
            guards.extend(self._compile_reversible_guards(skill))

        return guards

    def _compile_readonly_guards(self, skill: CompositeSkill) -> list[Guard]:
        """readonly skill 守卫：最宽松，只需确认 scope 匹配"""
        return [
            Guard(
                kind="param_check",
                expr=self._extract_scope_keyword(skill),
                on_fail="escalate",
            ),
        ]

    def _compile_idempotent_guards(self, skill: CompositeSkill) -> list[Guard]:
        """idempotent skill 守卫：确认操作目标存在"""
        guards = []
        for step in skill.steps:
            verb = step.get("verb", "")
            if "shell.serve" in verb or "shell.net" in verb:
                guards.append(Guard(
                    kind="param_check",
                    expr="localhost",
                    on_fail="escalate",
                ))
                break
        return guards

    def _compile_reversible_guards(self, skill: CompositeSkill) -> list[Guard]:
        """reversible skill 守卫：最严格，需确认目标路径"""
        guards = []
        for step in skill.steps:
            verb = step.get("verb", "")
            if verb in ("write_file", "edit_file", "shell.mutate"):
                guards.append(Guard(
                    kind="param_check",
                    expr="/tmp",  # 只允许在 /tmp 下的反射写入
                    on_fail="escalate",
                ))
                break
        return guards

    def _extract_scope_keyword(self, skill: CompositeSkill) -> str:
        """从 skill 步骤中提取最能代表 scope 的关键词"""
        verbs = [s.get("verb", "") for s in skill.steps]
        if any("read" in v or "search" in v for v in verbs):
            return "看|读|查|分析|搜索|find"
        if any("write" in v for v in verbs):
            return "写|创建|生成"
        if any("shell.python" in v for v in verbs):
            return "运行|执行|python"
        return ""

    def try_upgrade_to_l3(self, skill: CompositeSkill, registry: SkillRegistry) -> bool:
        """
        尝试为 skill 编译守卫并升级到 L3。
        返回 True 表示升级成功。
        """
        if skill.level < 2:
            return False
        if skill.frozen:
            return False

        stats = skill.get_stats()
        # 升级条件：acceptance >= 95% + success >= 95% + invocations >= 30
        if stats.invocations < 30:
            return False
        if stats.acceptance_rate < 0.95:
            return False
        if stats.success_rate < 0.95:
            return False

        # 编译守卫
        guards = self.compile(skill)
        if not guards:
            return False

        # 写入并升级
        skill.guards = [g.to_dict() for g in guards]
        skill.level = 3
        registry._save()
        return True
