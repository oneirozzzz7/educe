"""
CompositeSkill — 多级形态进化架构

Skill 不只是文本描述。它是一个从 Hint 到 Pure-Reflex 的连续谱系：
  L0 Hint          → prompt 引导（当前）
  L1 Template      → 参数化模板，LLM 填空
  L2 Plan-Graph    → 执行图，LLM 一次性审批
  L3 Guarded-Reflex→ 带守卫的反射，仅守卫失败时唤醒 LLM
  L4 Pure-Reflex   → 完全旁路 LLM

同一个 skill 在生命周期中可升降级。升级保守（多重证据），降级激进（单次失败）。

设计原则（Opus 4.8 2026-06-18 讨论确认）：
- L2 是性价比最高的中间态：N 次 LLM 调用压缩为 1 次审批
- L3+ 的前提是"判断逻辑已完全外化为 guard"
- 安全红线：destructive 类永远不升 L3+
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════

@dataclass
class ActionTemplate:
    """参数化 action，L1+ 的基本单元"""
    action_type: str                  # shell/write_file/read_file/...
    params_template: dict = field(default_factory=dict)  # 含占位符 ${slot_name}
    param_slots: list[str] = field(default_factory=list)  # 需要填充的槽位
    description: str = ""
    rollback: dict | None = None      # 逆操作（L3+ 用）

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["rollback"] is None:
            del d["rollback"]
        return d


@dataclass
class Guard:
    """守卫条件，L3+ 升级的前提"""
    kind: str           # "file_exists" | "env_match" | "prev_success" | "param_check"
    expr: str           # 可求值断言
    on_fail: str = "escalate"  # "escalate" | "abort" | "fallback"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SkillStats:
    """统计账本 — 驱动升降级"""
    invocations: int = 0
    llm_acceptances: int = 0      # LLM 采纳（未改写）次数
    llm_patches: int = 0          # LLM 改写次数
    outcome_successes: int = 0
    outcome_failures: int = 0
    guard_passes: int = 0
    guard_failures: int = 0
    last_failure_ts: float = 0.0
    last_failure_reason: str = ""

    @property
    def acceptance_rate(self) -> float:
        total = self.llm_acceptances + self.llm_patches
        return self.llm_acceptances / max(total, 1)

    @property
    def patch_rate(self) -> float:
        total = self.llm_acceptances + self.llm_patches
        return self.llm_patches / max(total, 1)

    @property
    def success_rate(self) -> float:
        total = self.outcome_successes + self.outcome_failures
        return self.outcome_successes / max(total, 1)

    @property
    def guard_pass_rate(self) -> float:
        total = self.guard_passes + self.guard_failures
        return self.guard_passes / max(total, 1)

    def to_dict(self) -> dict:
        return asdict(self)


SAFETY_CLASSES = ("readonly", "idempotent", "reversible", "destructive")
MAX_LEVEL_BY_SAFETY = {"readonly": 4, "idempotent": 4, "reversible": 3, "destructive": 1}


@dataclass
class CompositeSkill:
    """多级形态的编译技能"""
    # 身份
    skill_id: str
    name: str
    version: int = 1

    # 形态
    level: int = 0                     # 0-4 当前成熟度
    scope: str = ""                    # task_type 域
    safety_class: str = "reversible"   # see SAFETY_CLASSES

    # L0: 纯文本描述
    hint_text: str = ""

    # L1+: 参数化步骤
    steps: list[dict] = field(default_factory=list)  # [ActionTemplate.to_dict()]

    # L2+: 执行图（节点=steps索引，边=条件）
    graph_edges: list[tuple] = field(default_factory=list)  # [(from_idx, to_idx, condition)]

    # L3+: 守卫
    guards: list[dict] = field(default_factory=list)  # [Guard.to_dict()]

    # 触发
    trigger_scope: list[str] = field(default_factory=list)  # 允许的 task_type 列表
    trigger_keywords: list[str] = field(default_factory=list)
    position_hint: str = "anywhere"    # starter/positional/anywhere

    # 统计
    stats: dict = field(default_factory=dict)  # SkillStats.to_dict()

    # 治理
    approved_max_level: int = 2        # 治理层批准的天花板（默认最高 L2）
    frozen: bool = False
    created_at: float = field(default_factory=time.time)

    # 兼容旧字段
    confidence: float = 0.0
    support: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CompositeSkill":
        # 向后兼容旧格式
        if "level" not in d:
            d.setdefault("level", 0)
        if "hint_text" not in d:
            d["hint_text"] = d.get("trigger_description", "")
        # 去掉旧字段
        d.pop("trigger_description", None)
        d.pop("times_activated", None)
        d.pop("times_succeeded", None)
        # 兼容 stats
        if "stats" not in d or not d["stats"]:
            d["stats"] = {}
        # 兼容 trigger
        if "trigger_scope" not in d:
            d["trigger_scope"] = [d.get("scope", "")] if d.get("scope") else []
        if "trigger_keywords" not in d:
            d["trigger_keywords"] = []
        d.setdefault("version", 1)
        d.setdefault("safety_class", "reversible")
        d.setdefault("graph_edges", [])
        d.setdefault("guards", [])
        d.setdefault("approved_max_level", 2)
        d.setdefault("frozen", False)
        # 过滤无效字段
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        d = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**d)

    def get_stats(self) -> SkillStats:
        return SkillStats(**self.stats) if self.stats else SkillStats()

    def set_stats(self, s: SkillStats) -> None:
        self.stats = s.to_dict()

    # ═══ 渲染（按 level 分发）═══

    def render_for_prompt(self) -> str:
        """渲染为 prompt 注入文本（L0/L1 用）"""
        if self.level == 0:
            return self._render_l0()
        elif self.level >= 1:
            return self._render_l1()
        return ""

    def render_plan_graph(self) -> str:
        """渲染为完整执行计划（L2 用，供 LLM 一次性审批）"""
        lines = [f"【执行计划: {self.name}】"]
        for i, step in enumerate(self.steps):
            lines.append(f"  步骤{i+1}: {step.get('description', step.get('action_type', ''))}")
            if step.get("param_slots"):
                lines.append(f"         参数槽: {step['param_slots']}")
        lines.append("请审批此计划（直接执行/修改参数/拒绝）。")
        return "\n".join(lines)

    def _render_l0(self) -> str:
        if self.hint_text:
            return self.hint_text
        steps_text = "\n".join(
            f"  {i+1}. {s.get('description', s.get('verb', ''))}"
            for i, s in enumerate(self.steps)
        )
        return (
            f"【技能: {self.name}】\n"
            f"你可以一口气执行：\n{steps_text}\n"
            f"提示：直接输出所有步骤的 action，无需逐步等待确认。"
        )

    def _render_l1(self) -> str:
        steps_text = "\n".join(
            f"  {i+1}. [{s.get('action_type', s.get('verb', ''))}] {s.get('description', '')}"
            for i, s in enumerate(self.steps)
        )
        slots = set()
        for s in self.steps:
            slots.update(s.get("param_slots", []))
        slot_hint = f"\n  需要你填充: {', '.join(slots)}" if slots else ""
        return (
            f"【技能模板: {self.name}】\n"
            f"已知执行路径：\n{steps_text}{slot_hint}\n"
            f"请按此模板一口气输出所有 action，填入具体参数。"
        )

    # ═══ 升降级 ═══

    def check_upgrade(self) -> int | None:
        """检查是否满足升级条件，返回目标 level 或 None"""
        if self.frozen:
            return None
        s = self.get_stats()

        # 自动审批逻辑：readonly 类在统计证据充分时自动提升天花板到 L3
        effective_max = self._effective_max_level()

        if self.level == 0 and s.invocations >= 5:
            if len(self.steps) > 0:
                return 1
        elif self.level == 1 and s.invocations >= 10:
            if s.acceptance_rate >= 0.8 and s.patch_rate <= 0.2:
                return min(2, effective_max)
        elif self.level == 2 and s.invocations >= 30:
            if s.acceptance_rate >= 0.95 and s.success_rate >= 0.95 and self.guards:
                return min(3, effective_max)

        return None

    def _effective_max_level(self) -> int:
        """
        计算有效天花板（考虑自动审批）。

        规则（Opus 4.8 讨论确认）：
        - readonly + 统计证据充分 → 自动 +1（每次只升一级），硬顶 L3
        - 其他 safety_class → 维持 approved_max_level（需人工审批）
        - L4 无论如何需人工
        """
        base = min(self.approved_max_level, MAX_LEVEL_BY_SAFETY.get(self.safety_class, 1))
        if self.safety_class != "readonly":
            return base

        s = self.get_stats()
        # readonly 自动审批条件：inv≥50, acc≥98%, success≥98%, 近30次无failure
        if (s.invocations >= 50
            and s.acceptance_rate >= 0.98
            and s.success_rate >= 0.98
            and (time.time() - s.last_failure_ts > 300 or s.outcome_failures == 0)):
            auto_max = min(base + 1, 3)  # 硬顶 L3，不自动到 L4
            return auto_max

        return base

    def check_demotion(self) -> int | None:
        """
        对称降级检查（L3 守卫）。

        L3 运行中：
        - 单次 failure → 立即降回 L2
        - 滑动窗口 acc < 97%（近20次中 patches > 0.6） → 降回 L2
        返回目标 level（降级）或 None（不变）。
        """
        if self.level < 3:
            return None

        s = self.get_stats()

        # 条件1：最近有 failure（5分钟内）
        if s.outcome_failures > 0 and (time.time() - s.last_failure_ts < 300):
            return 2

        # 条件2：近期 acc 滑窗跌破阈值
        recent_total = s.llm_acceptances + s.llm_patches
        if recent_total >= 20 and s.acceptance_rate < 0.97:
            return 2

        return None

    def record_outcome(self, success: bool, accepted: bool = True, patched: bool = False) -> None:
        """记录一次激活结果"""
        s = self.get_stats()
        s.invocations += 1
        if success:
            s.outcome_successes += 1
        else:
            s.outcome_failures += 1
            s.last_failure_ts = time.time()
        if accepted and not patched:
            s.llm_acceptances += 1
        elif patched:
            s.llm_patches += 1
        self.set_stats(s)

        # 对称降级：L3 出现 failure 立即降
        if self.level >= 3:
            demotion = self.check_demotion()
            if demotion is not None:
                self.level = demotion
                return

        # 通用降级：单次失败降一级
        if not success and self.level > 0:
            self.level = max(0, self.level - 1)

        # 淘汰：连续多次失败
        if s.invocations >= 5 and s.success_rate < 0.3:
            self.confidence *= 0.5


# ═══════════════════════════════════════
#  编译器
# ═══════════════════════════════════════

class SkillCompiler:
    """将 PathCandidate 编译为 CompositeSkill"""

    _VERB_DESCRIPTIONS = {
        "shell.mutate": "创建目录/移动文件",
        "shell.python": "运行 Python 脚本",
        "shell.search": "搜索文件/代码",
        "shell.nav": "浏览目录结构",
        "shell.read": "读取文件内容",
        "shell.pkg": "安装依赖包",
        "shell.serve": "启动服务",
        "shell.net": "网络请求",
        "shell.git": "Git 操作",
        "shell.test": "运行测试",
        "shell.build": "构建项目",
        "shell.heredoc": "写入多行文件",
        "shell.write": "写入/追加内容",
        "write_file": "写入文件",
        "edit_file": "编辑文件",
        "read_lines": "读取代码行",
        "read_file": "读取整个文件",
        "read_dir": "列出目录",
        "search_in_file": "文件内搜索",
        "use_tool": "调用工具",
    }

    _SAFETY_MAP = {
        "shell.mutate": "reversible",
        "write_file": "reversible",
        "edit_file": "reversible",
        "shell.pkg": "reversible",
        "shell.serve": "idempotent",
        "read_lines": "readonly",
        "read_file": "readonly",
        "read_dir": "readonly",
        "search_in_file": "readonly",
        "shell.search": "readonly",
        "shell.nav": "readonly",
        "shell.read": "readonly",
        "shell.python": "reversible",
        "shell.net": "idempotent",
    }

    def compile(self, candidate: "PathCandidate", max_support: int = 30) -> CompositeSkill:
        from educe.core.metabolism.path_miner import PathCandidate as PC

        steps = []
        worst_safety = "readonly"
        for sig in candidate.steps:
            desc = self._describe_step(sig)
            action_type = sig.verb.split(".")[0] if "." in sig.verb else sig.verb
            steps.append({
                "action_type": action_type,
                "verb": sig.verb,
                "outcome": sig.outcome,
                "rdelta": sig.rdelta,
                "description": desc,
                "param_slots": [],
                "params_template": {},
            })
            step_safety = self._SAFETY_MAP.get(sig.verb, "reversible")
            if SAFETY_CLASSES.index(step_safety) > SAFETY_CLASSES.index(worst_safety):
                worst_safety = step_safety

        name = self._generate_name(candidate)
        position_hint = "starter" if candidate.position.is_starter else (
            "positional" if candidate.position.is_positional else "anywhere")
        keywords = self._extract_keywords(candidate)

        return CompositeSkill(
            skill_id=f"cs_{hash(tuple(s.to_tuple() for s in candidate.steps)) & 0xFFFFFF:06x}",
            name=name,
            level=0,
            scope=candidate.scope,
            safety_class=worst_safety,
            steps=steps,
            trigger_scope=[candidate.scope],
            trigger_keywords=keywords,
            position_hint=position_hint,
            confidence=min(candidate.support / max(max_support, 1), 1.0),
            support=candidate.support,
        )

    def _describe_step(self, sig) -> str:
        base = self._VERB_DESCRIPTIONS.get(sig.verb, sig.verb)
        if sig.outcome == "err":
            base += "（可能失败）"
        if sig.rdelta == "+file":
            base += " → 产生文件"
        elif sig.rdelta == "read":
            base += " → 读取信息"
        return base

    def _generate_name(self, candidate) -> str:
        verbs = [s.verb for s in candidate.steps]
        if "write_file" in verbs and "shell.pkg" in verbs:
            return "项目初始化"
        if "shell.search" in verbs and "read_lines" in verbs:
            return "代码探索"
        if "shell.mutate" in verbs and "write_file" in verbs:
            return "文件脚手架"
        if verbs.count("read_lines") >= 2:
            return "连续代码阅读"
        if "write_file" in verbs and "shell.python" in verbs:
            return "编写并运行"
        if "edit_file" in verbs:
            return "代码修改"
        return f"{candidate.scope}域多步操作"

    def _extract_keywords(self, candidate) -> list[str]:
        verbs = [s.verb for s in candidate.steps]
        kw = []
        if "write_file" in verbs:
            kw.extend(["写", "创建", "生成"])
        if "shell.python" in verbs:
            kw.extend(["运行", "执行", "脚本", "python"])
        if "shell.pkg" in verbs:
            kw.extend(["安装", "依赖"])
        if "read_lines" in verbs or "search_in_file" in verbs:
            kw.extend(["看", "读", "查看", "分析"])
        if "shell.mutate" in verbs:
            kw.extend(["创建", "目录", "项目"])
        if "shell.serve" in verbs:
            kw.extend(["启动", "服务"])
        return kw


# ═══════════════════════════════════════
#  注册表
# ═══════════════════════════════════════

class SkillRegistry:
    """CompositeSkill 持久化注册表"""

    def __init__(self, base_dir: Path | None = None):
        self._dir = base_dir or Path(".educe/skills")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "composite_skills.json"
        self._skills: dict[str, CompositeSkill] = {}
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                for d in data:
                    skill = CompositeSkill.from_dict(d)
                    self._skills[skill.skill_id] = skill
            except Exception:
                pass

    def _save(self) -> None:
        data = [s.to_dict() for s in self._skills.values()]
        self._file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def register(self, skill: CompositeSkill) -> None:
        self._skills[skill.skill_id] = skill
        self._save()

    def register_batch(self, skills: list[CompositeSkill]) -> None:
        for s in skills:
            self._skills[s.skill_id] = s
        self._save()

    def get(self, skill_id: str) -> CompositeSkill | None:
        return self._skills.get(skill_id)

    def all(self) -> list[CompositeSkill]:
        return list(self._skills.values())

    def match(self, scope: str, is_start: bool = False) -> list[CompositeSkill]:
        """匹配可用技能"""
        matched = []
        for skill in self._skills.values():
            if skill.frozen:
                continue
            if skill.confidence < 0.1:
                continue
            if scope not in skill.trigger_scope and skill.scope != scope:
                continue
            if skill.position_hint == "starter" and not is_start:
                continue
            matched.append(skill)
        matched.sort(key=lambda s: (-s.level, -s.confidence))
        return matched

    def record_activation(self, skill_id: str, success: bool) -> None:
        skill = self._skills.get(skill_id)
        if skill:
            skill.record_outcome(success=success)
            # 检查升级
            target = skill.check_upgrade()
            if target is not None and target > skill.level:
                skill.level = target
            self._save()

    @property
    def count(self) -> int:
        return len(self._skills)
