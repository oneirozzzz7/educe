"""
CompositeSkill — 阶段2的核心产物

由路径挖掘器发现的 PathCandidate 编译而成。
作用：在决策前注入 prompt，引导模型对熟悉任务一口气执行多步，
跳过逐步决策的来回。

与 BehaviorManifest 的关系：
- BehaviorManifest（阶段1）= 单条规则 if-then → 决策偏置
- CompositeSkill（阶段2）= 多步序列模板 → 决策加速
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from educe.core.metabolism.context_sig import StepSig, task_type, project_sig


@dataclass
class CompositeSkill:
    """编译后的多步技能"""
    skill_id: str
    name: str                          # 人类可读名称
    scope: str                         # task_type 域
    steps: list[dict]                  # [{verb, outcome, rdelta, description}]
    trigger_description: str           # 何时激活的自然语言描述
    confidence: float                  # 置信度 (support / max_support)
    support: int                       # 跨 session 出现次数
    position_hint: str                 # "starter" | "positional" | "anywhere"
    created_at: float = field(default_factory=time.time)
    times_activated: int = 0
    times_succeeded: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CompositeSkill":
        return cls(**d)

    def render_for_prompt(self) -> str:
        """渲染为可注入 prompt 的文本"""
        steps_text = "\n".join(
            f"  {i+1}. {s['description']}" for i, s in enumerate(self.steps)
        )
        return (
            f"【技能: {self.name}】(置信度 {self.confidence:.0%})\n"
            f"当任务属于 {self.scope} 域时，你可以一口气执行：\n"
            f"{steps_text}\n"
            f"提示：直接输出所有步骤的 action，无需逐步等待确认。"
        )


class SkillCompiler:
    """将 PathCandidate 编译为 CompositeSkill"""

    # 动词到自然语言的映射
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

    def compile(self, candidate: "PathCandidate", max_support: int = 30) -> CompositeSkill:
        """将一个 PathCandidate 编译为 CompositeSkill"""
        from educe.core.metabolism.path_miner import PathCandidate as PC

        steps = []
        for sig in candidate.steps:
            desc = self._describe_step(sig)
            steps.append({
                "verb": sig.verb,
                "outcome": sig.outcome,
                "rdelta": sig.rdelta,
                "description": desc,
            })

        # 生成名称
        name = self._generate_name(candidate)

        # 位置提示
        if candidate.position.is_starter:
            position_hint = "starter"
        elif candidate.position.is_positional:
            position_hint = "positional"
        else:
            position_hint = "anywhere"

        # 触发描述
        trigger = self._generate_trigger(candidate, position_hint)

        return CompositeSkill(
            skill_id=f"cs_{hash(tuple(s.to_tuple() for s in candidate.steps)) & 0xFFFFFF:06x}",
            name=name,
            scope=candidate.scope,
            steps=steps,
            trigger_description=trigger,
            confidence=min(candidate.support / max(max_support, 1), 1.0),
            support=candidate.support,
            position_hint=position_hint,
        )

    def _describe_step(self, sig: StepSig) -> str:
        base = self._VERB_DESCRIPTIONS.get(sig.verb, sig.verb)
        if sig.outcome == "err":
            base += "（可能失败，需重试）"
        if sig.rdelta == "+file":
            base += " → 产生文件"
        elif sig.rdelta == "read":
            base += " → 读取信息"
        return base

    def _generate_name(self, candidate: "PathCandidate") -> str:
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

    def _generate_trigger(self, candidate: "PathCandidate", position_hint: str) -> str:
        parts = []
        if position_hint == "starter":
            parts.append("任务开始时")
        parts.append(f"在 {candidate.scope} 域任务中")
        if candidate.mean_reward > 0.9:
            parts.append("高成功率路径")
        return "，".join(parts)


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
        """根据当前 scope 和位置匹配可用技能"""
        matched = []
        for skill in self._skills.values():
            if skill.scope != scope:
                continue
            if skill.position_hint == "starter" and not is_start:
                continue
            matched.append(skill)
        matched.sort(key=lambda s: -s.confidence)
        return matched

    def record_activation(self, skill_id: str, success: bool) -> None:
        skill = self._skills.get(skill_id)
        if skill:
            skill.times_activated += 1
            if success:
                skill.times_succeeded += 1
            self._save()

    @property
    def count(self) -> int:
        return len(self._skills)
