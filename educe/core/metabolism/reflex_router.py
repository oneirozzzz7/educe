"""
ReflexRouter — LLM 入口前的分诊器（阶段3基础设施）

执行循环的介入点D：在 LLM 调用前先尝试匹配 L3/L4 skill。
- 命中 L4 → 直接执行，LLM 完全未唤醒
- 命中 L3 → 检查守卫，通过则执行，失败则降级唤醒 LLM
- 未命中 → 透传，正常进入 LLM 路径

当前版本：框架 + 透传。L3/L4 skill 尚未产生时 passthrough。
接口已预留，阶段3 实现 Guard 编译器后可直接接入。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from educe.core.metabolism.composite_skill import CompositeSkill, SkillRegistry
from educe.core.metabolism.context_sig import task_type

log = logging.getLogger("educe.reflex")


@dataclass
class ReflexResult:
    """反射执行结果"""
    handled: bool = False           # True = 已处理，不需要 LLM
    response: str = ""              # 给用户的回复
    actions_executed: list = None   # 已执行的 action 列表
    skill_id: str = ""              # 匹配的 skill
    guard_failed: bool = False      # 守卫失败（需降级到 LLM）
    escalation_hint: str = ""       # 降级时给 LLM 的提示

    def __post_init__(self):
        if self.actions_executed is None:
            self.actions_executed = []


class ReflexRouter:
    """
    LLM 入口前分诊器。

    调用方式：
        router = ReflexRouter(registry)
        result = await router.try_reflex(user_input, context)
        if result.handled:
            return result.response  # 跳过 LLM
        elif result.guard_failed:
            # 把失败信息附加到 LLM prompt
            system += result.escalation_hint
        # else: 正常走 LLM
    """

    def __init__(self, registry: SkillRegistry):
        self._registry = registry
        self._stats = {"attempts": 0, "hits": 0, "guard_fails": 0, "passthrough": 0}

    async def try_reflex(
        self,
        user_input: str,
        context: dict | None = None,
    ) -> ReflexResult:
        """尝试反射执行，返回 ReflexResult"""
        self._stats["attempts"] += 1

        # 匹配 L3+ skill
        scope = task_type(user_input)
        candidates = self._registry.match(scope, is_start=True)
        reflex_skills = [s for s in candidates if s.level >= 3 and not s.frozen]

        if not reflex_skills:
            self._stats["passthrough"] += 1
            return ReflexResult(handled=False)

        # 选最高置信度的 L3+ skill
        best = reflex_skills[0]
        log.info(f"ReflexRouter: matched L{best.level} skill '{best.name}' for scope={scope}")

        # 检查守卫
        guard_result = self._check_guards(best, user_input, context or {})
        if not guard_result:
            # 守卫失败 → 降级
            self._stats["guard_fails"] += 1
            best.record_outcome(success=False)
            self._registry._save()
            return ReflexResult(
                handled=False,
                guard_failed=True,
                skill_id=best.skill_id,
                escalation_hint=(
                    f"\n[系统] 反射技能'{best.name}'的守卫检查未通过，"
                    f"请正常处理此请求。"
                ),
            )

        # 守卫通过 → 执行反射
        self._stats["hits"] += 1
        result = await self._execute_reflex(best, user_input, context or {})
        return result

    def _check_guards(
        self, skill: CompositeSkill, user_input: str, context: dict
    ) -> bool:
        """检查 skill 的所有守卫条件"""
        if not skill.guards:
            # 无守卫的 L3+ skill 不应该存在，但保守处理
            return skill.level >= 4  # L4 允许无守卫（纯 readonly）

        for guard in skill.guards:
            kind = guard.get("kind", "")
            expr = guard.get("expr", "")

            if kind == "prev_success":
                # 检查上一次执行是否成功
                stats = skill.get_stats()
                if stats.outcome_failures > 0 and stats.last_failure_ts > time.time() - 300:
                    return False

            elif kind == "param_check":
                # 检查输入是否匹配预期参数范围（支持 | 分隔的多关键词）
                import re
                if expr and not re.search(expr, user_input.lower()):
                    return False

            elif kind == "file_exists":
                # 检查文件是否存在
                from pathlib import Path
                if expr and not Path(expr).exists():
                    return False

        return True

    async def _execute_reflex(
        self, skill: CompositeSkill, user_input: str, context: dict
    ) -> ReflexResult:
        """
        执行反射动作（公理五：Schema 驱动 + 事实验证 + LLM 降级）

        不用正则猜测自然语言。而是：
        1. 从 user_input 中提取候选 token
        2. 用事实验证（os.path.exists）确认 filepath
        3. 剩余 token 中取标识符作为 keyword
        4. 抠不到 → 诚实降级到 LLM
        """
        import os
        import subprocess

        if skill.safety_class != "readonly":
            skill.record_outcome(success=True, accepted=True)
            self._registry._save()
            return ReflexResult(
                handled=False,
                skill_id=skill.skill_id,
                escalation_hint=(
                    f"\n[系统反射提示] 此任务匹配已验证路径'{skill.name}'(L{skill.level})，"
                    f"请直接执行，无需探索。"
                ),
            )

        # === Schema 驱动参数提取 ===
        # 不猜"什么长得像路径"，而是验证"什么真实存在"
        target_path, keyword = self._extract_params_by_probe(user_input)

        # 构造命令
        if keyword and target_path:
            if keyword.lower() in os.path.basename(target_path).lower():
                cmd = f"cat {target_path} 2>/dev/null | head -50"
            else:
                cmd = f"grep -rn '{keyword}' {target_path} 2>/dev/null | head -20"
        elif target_path:
            cmd = f"cat {target_path} 2>/dev/null | head -50"
        else:
            return ReflexResult(
                handled=False,
                skill_id=skill.skill_id,
                escalation_hint=f"\n[反射] 无法从输入中验证出真实路径，降级到 LLM。",
            )

        # 执行
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10,
                cwd=context.get("cwd", "."),
            )
            output = result.stdout.strip() or "(无输出)"
            success = result.returncode == 0

            skill.record_outcome(success=success, accepted=True)
            self._registry._save()

            if success and output:
                log.info(f"ReflexRouter: L3 direct execution SUCCESS for '{skill.name}'")
                return ReflexResult(
                    handled=True,
                    response=f"[反射执行] {cmd}\n\n```\n{output}\n```",
                    actions_executed=[{"type": "shell", "cmd": cmd, "exit": result.returncode}],
                    skill_id=skill.skill_id,
                )
            else:
                return ReflexResult(
                    handled=False,
                    skill_id=skill.skill_id,
                    escalation_hint=f"\n[反射失败] 命令返回码={result.returncode}，降级到 LLM。",
                )

        except Exception as e:
            skill.record_outcome(success=False)
            self._registry._save()
            return ReflexResult(
                handled=False,
                skill_id=skill.skill_id,
                escalation_hint=f"\n[反射异常] {e}，降级到 LLM。",
            )

    def _extract_params_by_probe(self, user_input: str) -> tuple[str, str]:
        """
        事实验证式参数提取（公理五：验证真实存在，不猜测）

        从 user_input 的 token 中：
        1. 找到真实存在于文件系统的路径 → target_path
        2. 从剩余 token 中提取英文标识符 → keyword
        """
        import os

        tokens = user_input.replace("，", " ").replace("。", " ").split()
        target_path = ""
        keyword = ""
        used_indices = set()

        # Pass 1: 事实验证——哪个 token 是真实存在的文件路径
        for i, tok in enumerate(tokens):
            candidate = tok.strip("\"'`，。！？")
            if "/" in candidate or "." in candidate:
                if os.path.exists(candidate):
                    target_path = candidate
                    used_indices.add(i)
                    break
                # 尝试常见前缀
                for prefix in ["/tmp/", "./", os.getcwd() + "/"]:
                    full = prefix + candidate.lstrip("./")
                    if os.path.exists(full):
                        target_path = full
                        used_indices.add(i)
                        break
                if target_path:
                    break

        # Pass 2: 从剩余 token 提取英文标识符
        for i, tok in enumerate(tokens):
            if i in used_indices:
                continue
            clean = tok.strip("\"'`，。！？")
            if len(clean) >= 3 and clean[0].isalpha() and clean.replace("_", "").isalnum():
                if not clean.endswith(("py", "js", "ts", "md")):
                    keyword = clean
                    break

        return target_path, keyword

    @property
    def stats(self) -> dict:
        return self._stats.copy()
