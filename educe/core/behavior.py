"""
Behavior Manifest — Agent 行为的一等公民

核心理念：Agent 的"聪明"不是一段 prompt，而是一组可版本化的行为规则。
每条规则有明确的触发条件、行为指令、学习出处、置信度。

设计原则：
- 可序列化（YAML/JSON 存盘）
- 可 diff（unit 级别的增删改）
- 可恢复（加载后行为可复现）
- 可传递（clone/push/pull 到其他 Agent）
- 可审计（每条规则有 evidence 溯源）
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger("educe.behavior")


class UnitStatus(str, Enum):
    STAGED = "staged"      # 刚学到，未验证
    ACTIVE = "active"      # 验证通过，生效中
    ARCHIVED = "archived"  # 被淘汰/手动归档


@dataclass
class BehaviorUnit:
    """一条行为规则 — Agent 行为的原子单位"""

    id: str                          # 唯一标识
    trigger: str                     # 什么情况下激活（自然语言条件）
    directive: str                   # 激活后做什么（自然语言指令）
    evidence: list[str] = field(default_factory=list)  # 学习出处（episode ids）
    weight: float = 0.5             # 置信度 [0, 1]，高=更可靠
    status: UnitStatus = UnitStatus.STAGED

    # 元数据
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_hit_at: float = 0.0        # 最后一次被触发的时间（0=从未触发）
    hit_count: int = 0              # 被触发次数
    success_count: int = 0          # 触发后下游成功次数
    fail_count: int = 0             # 触发后下游失败次数
    parent_id: Optional[str] = None # 由哪条 unit 演化来的
    conflicts_with: list[str] = field(default_factory=list)  # 冲突的 unit ids

    # 边际归因（Marginal Attribution）
    baseline_tests: int = 0         # 静默对照次数（匹配但未注入）
    baseline_passes: int = 0        # 静默对照中模型自主遵守的次数

    # Output-Metric Attribution（分布式归因）
    effect_dimension: Optional[str] = None   # 影响的输出维度（length/emoji_count/...）
    effect_direction: int = -1               # -1=规则应减少该维度, +1=应增加
    inject_samples: list[float] = field(default_factory=list)   # 注入时的度量采样
    withhold_samples: list[float] = field(default_factory=list) # 未注入时的度量采样

    MAX_SAMPLES = 30  # 每组最多保留 30 个样本（ring buffer）

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def marginal_value(self) -> float:
        """边际价值：规则注入对输出的因果效应

        优先使用 output-metric（分布对比 Cohen's d），
        fallback 到 binary user-signal 方法。
        """
        # 方法1：Output-Metric（有 effect_dimension 且样本充足）
        if self.effect_dimension and len(self.inject_samples) >= 5 and len(self.withhold_samples) >= 5:
            return self._metric_marginal_value()

        # 方法2：Binary user-signal fallback
        return self._signal_marginal_value()

    def _metric_marginal_value(self) -> float:
        """基于输出度量的分布对比（Cohen's d）"""
        inject_mean = sum(self.inject_samples) / len(self.inject_samples)
        withhold_mean = sum(self.withhold_samples) / len(self.withhold_samples)

        # Pooled standard deviation
        n1, n2 = len(self.inject_samples), len(self.withhold_samples)
        var1 = sum((x - inject_mean) ** 2 for x in self.inject_samples) / max(1, n1 - 1)
        var2 = sum((x - withhold_mean) ** 2 for x in self.withhold_samples) / max(1, n2 - 1)
        pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / max(1, n1 + n2 - 2)
        pooled_std = pooled_var ** 0.5

        if pooled_std < 1e-6:
            return 0.0

        # effect_direction=-1: 规则应减少该值 → inject < withhold = 好
        # effect_direction=+1: 规则应增加该值 → inject > withhold = 好
        raw_d = (inject_mean - withhold_mean) * self.effect_direction / pooled_std

        # Normalize: d=0.5 (medium effect) → mv≈0.5, d>=1.0 → mv=1.0
        return max(0.0, min(1.0, raw_d))

    def _signal_marginal_value(self) -> float:
        """Bayesian binary 方法（fallback，用于无法度量的规则）"""
        PRIOR_STRENGTH = 3
        PRIOR_MEAN = 0.3

        inject_tests = self.success_count + self.fail_count
        inject_passes = self.success_count
        bt = self.baseline_tests
        bp = self.baseline_passes

        if inject_tests == 0:
            p_inject = PRIOR_MEAN + 0.3
        else:
            p_inject = (inject_passes + PRIOR_STRENGTH * 0.6) / (inject_tests + PRIOR_STRENGTH)

        if bt == 0:
            p_baseline = PRIOR_MEAN
        else:
            p_baseline = (bp + PRIOR_STRENGTH * PRIOR_MEAN) / (bt + PRIOR_STRENGTH)

        return max(0.0, min(1.0, p_inject - p_baseline))

    def record_metric_sample(self, value: float, injected: bool) -> None:
        """记录一次输出度量采样"""
        if injected:
            self.inject_samples.append(value)
            if len(self.inject_samples) > self.MAX_SAMPLES:
                self.inject_samples = self.inject_samples[-self.MAX_SAMPLES:]
        else:
            self.withhold_samples.append(value)
            if len(self.withhold_samples) > self.MAX_SAMPLES:
                self.withhold_samples = self.withhold_samples[-self.MAX_SAMPLES:]

    @property
    def effective_weight(self) -> float:
        """时间衰减后的有效权重 — 不用的器官会萎缩"""
        if self.last_hit_at <= 0:
            return self.weight
        idle_days = (time.time() - self.last_hit_at) / 86400
        # 7 天半衰期：idle_days=7 → decay=0.5, idle_days=14 → decay=0.25
        decay = 0.5 ** (idle_days / 7.0)
        return self.weight * decay

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BehaviorUnit":
        d["status"] = UnitStatus(d.get("status", "staged"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BehaviorCommit:
    """一次行为变更的快照 — 等价于 git commit"""

    commit_id: str
    message: str                     # 自动生成的变更摘要（"learned: X"）
    timestamp: float
    parent_id: Optional[str] = None  # 前一个 commit
    diff: list[dict] = field(default_factory=list)  # 变更列表 [{op, unit_id, before, after}]
    manifest_snapshot_hash: str = "" # 对应的 manifest 状态哈希

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BehaviorCommit":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BehaviorManifest:
    """Agent 的完整行为描述 — 等价于 git 仓库的工作区状态"""

    agent_id: str
    base_seed: str                   # 基础人格/能力描述（unit 列表的兜底）
    units: list[BehaviorUnit] = field(default_factory=list)
    commits: list[BehaviorCommit] = field(default_factory=list)
    version: int = 0

    # ═══ 读取行为 ═══

    def active_units(self) -> list[BehaviorUnit]:
        """获取所有生效中的行为规则"""
        return [u for u in self.units if u.status == UnitStatus.ACTIVE]

    def staged_units(self) -> list[BehaviorUnit]:
        """获取待验证的行为规则"""
        return [u for u in self.units if u.status == UnitStatus.STAGED]

    def get_unit(self, unit_id: str) -> Optional[BehaviorUnit]:
        for u in self.units:
            if u.id == unit_id:
                return u
        return None

    def match_units(self, context: str) -> list[BehaviorUnit]:
        """根据当前上下文匹配相关的行为规则（简单关键词匹配，后续可升级）"""
        matched = []
        context_lower = context.lower()
        for u in self.active_units():
            # 时间衰减后权重过低的 unit 跳过（自然萎缩）
            if u.effective_weight < 0.05:
                continue
            trigger_keywords = set(u.trigger.lower().split())
            if len(trigger_keywords) <= 2:
                if all(kw in context_lower for kw in trigger_keywords if len(kw) > 1):
                    matched.append(u)
            else:
                overlap = sum(1 for kw in trigger_keywords if kw in context_lower and len(kw) > 1)
                if overlap >= len(trigger_keywords) * 0.5:
                    matched.append(u)
        # 按注入优先级排序：marginal_value × effective_weight × token_efficiency
        def _injection_priority(u):
            mv = u.marginal_value
            ew = u.effective_weight
            token_eff = 1.0 / max(len(u.directive) / 20, 1.0)
            return mv * ew * token_eff
        matched.sort(key=_injection_priority, reverse=True)
        return matched

    def render_for_prompt(self, context: str = "", max_tokens: int = 300) -> str:
        """将行为规则渲染为注入 prompt 的文本

        设计哲学：全量注入 active + staged 规则，让模型自己做 NLI 判断适用性。
        staged 规则需要试用机会才能积累数据晋升。
        仅做冲突过滤和 token 预算裁剪。
        """
        parts = [self.base_seed]

        # active 优先，staged 也参与（需要试用机会来积累 reinforce 数据）
        candidates = self.active_units() + self.staged_units()
        def _injection_priority(u):
            mv = u.marginal_value
            ew = u.effective_weight
            token_eff = 1.0 / max(len(u.directive) / 20, 1.0)
            # staged 规则降权（给它试用机会但不抢 active 的位子）
            status_factor = 1.0 if u.status == UnitStatus.ACTIVE else 0.5
            return mv * ew * token_eff * status_factor
        candidates.sort(key=_injection_priority, reverse=True)

        if candidates:
            parts.append("\n## 经验教训（供参考，你有权根据具体情况判断是否适用）")
            budget_used = 0
            injected_directives: list[str] = []
            for u in candidates:
                if self._conflicts_with_injected(u.directive, injected_directives):
                    continue
                line = f"- {u.directive}"
                line_tokens = len(line) // 2
                if budget_used + line_tokens > max_tokens:
                    break
                parts.append(line)
                injected_directives.append(u.directive)
                budget_used += line_tokens

        return "\n".join(parts)

    @staticmethod
    def _conflicts_with_injected(new_directive: str, existing: list[str]) -> bool:
        """粗粒度冲突检测：检查新规则是否和已注入的规则在关键维度矛盾"""
        if not existing:
            return False

        # 长度相关冲突
        length_increase = any(w in new_directive for w in ["详细", "完整", "展开", "深入"])
        length_decrease = any(w in new_directive for w in ["简短", "简洁", "字以内", "精简"])
        for ex in existing:
            if length_increase and any(w in ex for w in ["简短", "简洁", "字以内", "精简"]):
                return True
            if length_decrease and any(w in ex for w in ["详细", "完整", "展开", "深入"]):
                return True

        # 语言冲突
        force_chinese = any(w in new_directive for w in ["中文", "全中文"])
        force_english = any(w in new_directive for w in ["英文", "English", "全英文"])
        for ex in existing:
            if force_chinese and any(w in ex for w in ["英文", "English"]):
                return True
            if force_english and any(w in ex for w in ["中文"]):
                return True

        return False

    # ═══ 写入行为 ═══

    def add_unit(self, unit: BehaviorUnit, message: str = "") -> BehaviorCommit:
        """添加一条新行为规则并生成 commit"""
        self.units.append(unit)
        self.version += 1

        commit = BehaviorCommit(
            commit_id=uuid.uuid4().hex[:8],
            message=message or f"learn: {unit.trigger[:50]}",
            timestamp=time.time(),
            parent_id=self.commits[-1].commit_id if self.commits else None,
            diff=[{"op": "add", "unit_id": unit.id, "after": unit.to_dict()}],
        )
        self.commits.append(commit)
        log.info("Commit %s: %s", commit.commit_id, commit.message)
        return commit

    def update_unit(self, unit_id: str, **kwargs) -> Optional[BehaviorCommit]:
        """更新一条行为规则"""
        unit = self.get_unit(unit_id)
        if not unit:
            return None

        before = unit.to_dict()
        for k, v in kwargs.items():
            if hasattr(unit, k):
                setattr(unit, k, v)
        unit.updated_at = time.time()
        after = unit.to_dict()

        self.version += 1
        commit = BehaviorCommit(
            commit_id=uuid.uuid4().hex[:8],
            message=f"update: {unit.trigger[:40]}",
            timestamp=time.time(),
            parent_id=self.commits[-1].commit_id if self.commits else None,
            diff=[{"op": "update", "unit_id": unit_id, "before": before, "after": after}],
        )
        self.commits.append(commit)
        return commit

    def archive_unit(self, unit_id: str, reason: str = "") -> Optional[BehaviorCommit]:
        """归档（淘汰）一条行为规则"""
        return self.update_unit(unit_id, status=UnitStatus.ARCHIVED)

    # ═══ 版本控制操作 ═══

    def log(self, n: int = 20) -> list[BehaviorCommit]:
        """查看最近 N 条 commit"""
        return self.commits[-n:]

    def diff(self, commit_a_id: str, commit_b_id: str) -> list[dict]:
        """比较两个 commit 之间的差异"""
        # 收集两个 commit 之间所有 diff
        diffs = []
        in_range = False
        for c in self.commits:
            if c.commit_id == commit_a_id:
                in_range = True
                continue
            if in_range:
                diffs.extend(c.diff)
            if c.commit_id == commit_b_id:
                break
        return diffs

    def checkout(self, commit_id: str) -> "BehaviorManifest":
        """回到某个 commit 的状态（返回新 manifest，不修改当前）"""
        # 从头重放 commit 到目标点
        fresh = BehaviorManifest(
            agent_id=self.agent_id,
            base_seed=self.base_seed,
        )
        for c in self.commits:
            for d in c.diff:
                if d["op"] == "add":
                    fresh.units.append(BehaviorUnit.from_dict(d["after"]))
                elif d["op"] == "update":
                    unit = fresh.get_unit(d["unit_id"])
                    if unit:
                        for k, v in d["after"].items():
                            if hasattr(unit, k) and k != "id":
                                setattr(unit, k, v)
                elif d["op"] == "remove":
                    fresh.units = [u for u in fresh.units if u.id != d["unit_id"]]
            fresh.commits.append(c)
            if c.commit_id == commit_id:
                break
        return fresh

    # ═══ 持久化 ═══

    def save(self, path: Path) -> None:
        """保存到磁盘"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "agent_id": self.agent_id,
            "base_seed": self.base_seed,
            "version": self.version,
            "units": [u.to_dict() for u in self.units],
            "commits": [c.to_dict() for c in self.commits],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BehaviorManifest":
        """从磁盘加载"""
        data = json.loads(path.read_text(encoding="utf-8"))
        manifest = cls(
            agent_id=data["agent_id"],
            base_seed=data["base_seed"],
            version=data.get("version", 0),
        )
        manifest.units = [BehaviorUnit.from_dict(u) for u in data.get("units", [])]
        manifest.commits = [BehaviorCommit.from_dict(c) for c in data.get("commits", [])]
        return manifest

    # ═══ 统计 ═══

    def stats(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "total_units": len(self.units),
            "active": len(self.active_units()),
            "staged": len(self.staged_units()),
            "archived": sum(1 for u in self.units if u.status == UnitStatus.ARCHIVED),
            "commits": len(self.commits),
            "version": self.version,
        }
