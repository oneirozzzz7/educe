"""
BehaviorLearner — 从对话信号中自动提取行为规则

学习来源：
1. 用户纠正（"不对"、"应该这样"） → 提取 trigger + directive
2. 执行失败后重试成功 → 提取"遇到X，直接Y"
3. match 到 unit 后下游成功/失败 → 强化/惩罚权重
4. staged unit 成功率达标 → 提升为 active
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from deepforge.core.behavior import BehaviorManifest, BehaviorUnit, UnitStatus

log = logging.getLogger("educe.behavior_learner")

EXTRACT_PROMPT = """\
你是行为规则提取器。从用户的纠正中提取一条通用规则。

上下文：
- AI上一轮回答：{prev_response}
- 用户纠正：{user_correction}

提取一条行为规则，输出JSON：
{{
  "trigger": "什么情况下应该应用这条规则（通用描述，不要包含具体细节）",
  "directive": "应该怎么做（具体的行为指令）",
  "confidence": 0.0-1.0（这条规则的通用性，越通用越高）
}}

要求：
- trigger 要抽象化，能匹配同类场景（不是只匹配这一次）
- directive 要具体可执行
- 如果用户的纠正只是补充信息而非纠正行为，confidence 设为 0
- 只输出JSON"""

RETRY_EXTRACT_PROMPT = """\
你是行为规则提取器。从一次"失败→成功"的过程中提取经验。

失败的操作：{failed_action}
失败原因：{failure_reason}
成功的操作：{success_action}
上下文：{context}

提取一条规则，输出JSON：
{{
  "trigger": "什么情况下应该应用这条规则",
  "directive": "应该怎么做（避免失败的关键）",
  "confidence": 0.0-1.0
}}

只输出JSON"""


class BehaviorLearner:
    """从对话信号中提取行为规则并管理其生命周期"""

    PROMOTE_MIN_HITS = 3      # 至少被触发 N 次才考虑晋升
    ARCHIVE_MIN_HITS = 5      # 至少被触发 N 次才考虑归档
    MAX_ACTIVE_UNITS = 12     # active 上限（token 预算约束，不是越多越好）
    DECAY_HALF_LIFE_DAYS = 7  # 权重半衰期

    def __init__(self, manifest: BehaviorManifest, persist_path: Path):
        self.manifest = manifest
        self.persist_path = persist_path

    async def learn_from_correction(
        self, prev_response: str, user_correction: str, client, model: str
    ) -> Optional[BehaviorUnit]:
        """用户纠正时提取规则 → staged unit"""
        prompt = EXTRACT_PROMPT.format(
            prev_response=prev_response[:500],
            user_correction=user_correction[:500],
        )
        try:
            raw = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                max_tokens=200,
                temperature=0.0,
            )
            parsed = json.loads(raw.strip().strip("```json").strip("```"))
        except Exception as e:
            log.warning("learn_from_correction parse failed: %s", str(e)[:80])
            return None

        confidence = parsed.get("confidence", 0.0)
        if confidence < 0.3:
            log.info("learn_from_correction: low confidence %.2f, skip", confidence)
            return None

        trigger = parsed.get("trigger", "")
        directive = parsed.get("directive", "")
        if not trigger or not directive:
            return None

        # 去重：检查是否已有相似 trigger 的 unit
        if self._has_similar_unit(trigger):
            log.info("learn_from_correction: similar unit exists, skip")
            return None

        unit = BehaviorUnit(
            id=uuid.uuid4().hex[:8],
            trigger=trigger,
            directive=directive,
            evidence=[f"correction:{user_correction[:100]}"],
            weight=confidence * 0.5,  # 初始权重打折，验证后再升
            status=UnitStatus.STAGED,
        )
        commit = self.manifest.add_unit(unit, message=f"learn(correction): {trigger[:40]}")
        self._persist()
        log.info("Learned from correction: %s → %s [%s]", trigger[:40], directive[:40], commit.commit_id)
        return unit

    async def learn_from_retry(
        self, failed_action: str, failure_reason: str,
        success_action: str, context: str,
        client, model: str
    ) -> Optional[BehaviorUnit]:
        """失败后重试成功 → 提取经验"""
        prompt = RETRY_EXTRACT_PROMPT.format(
            failed_action=failed_action[:300],
            failure_reason=failure_reason[:200],
            success_action=success_action[:300],
            context=context[:200],
        )
        try:
            raw = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                max_tokens=200,
                temperature=0.0,
            )
            parsed = json.loads(raw.strip().strip("```json").strip("```"))
        except Exception as e:
            log.warning("learn_from_retry parse failed: %s", str(e)[:80])
            return None

        confidence = parsed.get("confidence", 0.0)
        if confidence < 0.3:
            return None

        trigger = parsed.get("trigger", "")
        directive = parsed.get("directive", "")
        if not trigger or not directive:
            return None

        if self._has_similar_unit(trigger):
            return None

        unit = BehaviorUnit(
            id=uuid.uuid4().hex[:8],
            trigger=trigger,
            directive=directive,
            evidence=[f"retry:{failed_action[:60]}→{success_action[:60]}"],
            weight=confidence * 0.5,
            status=UnitStatus.STAGED,
        )
        self.manifest.add_unit(unit, message=f"learn(retry): {trigger[:40]}")
        self._persist()
        log.info("Learned from retry: %s → %s", trigger[:40], directive[:40])
        return unit

    def reinforce(self, unit_id: str) -> None:
        """规则被注入且下游成功 → 增强（仅当有边际价值时）"""
        unit = self.manifest.get_unit(unit_id)
        if not unit:
            return
        unit.hit_count += 1
        unit.last_hit_at = time.time()

        # 反事实强化：如果边际价值太低（模型本来就会做），不增加 weight
        if unit.baseline_tests >= 5 and unit.marginal_value < 0.15:
            # 模型自主遵守率高 → 这次成功不归功于规则
            return

        unit.success_count += 1
        unit.weight = min(0.95, unit.weight + 0.05 * (1 - unit.weight))
        self._maybe_promote(unit)
        self._persist()

    def penalize(self, unit_id: str) -> None:
        """规则被注入但下游失败 → 减弱"""
        unit = self.manifest.get_unit(unit_id)
        if not unit:
            return
        unit.hit_count += 1
        unit.fail_count += 1
        unit.last_hit_at = time.time()
        # 权重下调
        unit.weight = max(0.05, unit.weight - 0.1)
        self._maybe_archive(unit)
        self._persist()

    def record_baseline(self, unit_id: str, compliant: bool) -> None:
        """静默对照：规则匹配但未注入，记录模型是否自主遵守"""
        unit = self.manifest.get_unit(unit_id)
        if not unit:
            return
        unit.baseline_tests += 1
        if compliant:
            unit.baseline_passes += 1
        unit.last_hit_at = time.time()
        self._persist()

    def should_withhold(self, unit_id: str) -> bool:
        """决定是否对该 unit 做静默对照（不注入）

        自适应频率：
        - hit_count < 2: 永不withhold（先让规则跑几轮建立 inject 数据）
        - baseline_tests < 5: 每3次命中withhold 1次（需要数据）
        - baseline_tests 5-15: 每5次1次
        - baseline_tests > 15: 每8次1次
        - marginal_value > 0.8 且数据充足: 不再withhold
        """
        unit = self.manifest.get_unit(unit_id)
        if not unit:
            return False

        # 前几次总是 inject（需要先积累 inject 数据才有对比意义）
        if unit.hit_count < 2:
            return False

        # 已证明高价值且数据充足 → 不再 withhold
        if unit.baseline_tests >= 10 and unit.marginal_value > 0.8:
            return False

        # 自适应频率
        bt = unit.baseline_tests
        if bt < 5:
            rate = 3
        elif bt < 15:
            rate = 5
        else:
            rate = 8

        # 确定性决策（基于 hit_count，可复现）
        return (unit.hit_count % rate) == 0

    def lifecycle_check(self) -> dict:
        """定期检查所有 units 的生命周期状态，返回变更摘要

        阈值是相对的：promote 门槛 = 群体 p75，archive 门槛 = 群体 p25。
        时间衰减：effective_weight < 0.03 的直接归档（自然萎缩）。
        """
        promoted = []
        archived = []

        # 计算相对阈值
        promote_threshold, archive_threshold = self._compute_thresholds()

        for unit in list(self.manifest.units):
            # 时间衰减归档：长期未使用 → 自然死亡
            if unit.status in (UnitStatus.STAGED, UnitStatus.ACTIVE):
                if unit.last_hit_at > 0 and unit.effective_weight < 0.03:
                    self.manifest.archive_unit(unit.id, reason="decayed")
                    archived.append(unit.id)
                    continue
                # 冗余归档：baseline 数据充足且边际价值极低 → 规则无用
                if unit.baseline_tests >= 8 and unit.marginal_value < 0.1:
                    self.manifest.archive_unit(unit.id, reason="redundant (low marginal_value)")
                    archived.append(unit.id)
                    continue

            if unit.status == UnitStatus.STAGED:
                if self._should_promote(unit, promote_threshold):
                    self.manifest.update_unit(unit.id, status=UnitStatus.ACTIVE)
                    promoted.append(unit.id)
                elif self._should_archive(unit, archive_threshold):
                    self.manifest.archive_unit(unit.id)
                    archived.append(unit.id)
            elif unit.status == UnitStatus.ACTIVE:
                if self._should_archive(unit, archive_threshold):
                    self.manifest.archive_unit(unit.id)
                    archived.append(unit.id)

        # 能量守恒：active 超过上限 → 淘汰 effective_weight 最低的
        active = self.manifest.active_units()
        if len(active) > self.MAX_ACTIVE_UNITS:
            active.sort(key=lambda u: u.effective_weight)
            for u in active[: len(active) - self.MAX_ACTIVE_UNITS]:
                self.manifest.archive_unit(u.id, reason="capacity overflow")
                archived.append(u.id)

        if promoted or archived:
            self._persist()

        return {"promoted": promoted, "archived": archived}

    def get_matched_units(self, context: str) -> list[BehaviorUnit]:
        """获取当前上下文匹配的 units（用于后续 reinforce/penalize）"""
        return self.manifest.match_units(context)

    def _compute_thresholds(self) -> tuple[float, float]:
        """从群体统计中计算相对阈值（不依赖 magic number）"""
        active = self.manifest.active_units()
        if len(active) < 3:
            # 初期数据不足，用保守默认值
            return 0.65, 0.25

        rates = sorted(u.success_rate for u in active if u.hit_count >= 2)
        if not rates:
            return 0.65, 0.25

        # promote = p75（优于群体 75% 才晋升）
        p75_idx = int(len(rates) * 0.75)
        promote = rates[min(p75_idx, len(rates) - 1)]
        # archive = p25（劣于群体 75% 才淘汰）
        p25_idx = int(len(rates) * 0.25)
        archive = rates[min(p25_idx, len(rates) - 1)]

        # 保底：promote 不低于 0.5，archive 不高于 0.4
        promote = max(0.5, promote)
        archive = min(0.4, archive)
        return promote, archive

    def _should_promote(self, unit: BehaviorUnit, threshold: float) -> bool:
        # 晋升条件：成功率达标 + 有边际价值（不是搭便车）
        mv_ok = unit.baseline_tests < 3 or unit.marginal_value >= 0.2
        return (
            unit.hit_count >= self.PROMOTE_MIN_HITS
            and unit.success_rate >= threshold
            and mv_ok
        )

    def _should_archive(self, unit: BehaviorUnit, threshold: float) -> bool:
        return (
            unit.hit_count >= self.ARCHIVE_MIN_HITS
            and unit.success_rate < threshold
        )

    def _maybe_promote(self, unit: BehaviorUnit) -> None:
        threshold, _ = self._compute_thresholds()
        if unit.status == UnitStatus.STAGED and self._should_promote(unit, threshold):
            self.manifest.update_unit(unit.id, status=UnitStatus.ACTIVE)
            log.info("Promoted unit %s to ACTIVE (rate=%.2f, threshold=%.2f)",
                     unit.id, unit.success_rate, threshold)

    def _maybe_archive(self, unit: BehaviorUnit) -> None:
        _, threshold = self._compute_thresholds()
        if self._should_archive(unit, threshold):
            self.manifest.archive_unit(unit.id, reason="low success rate")
            log.info("Archived unit %s (rate=%.2f, threshold=%.2f)",
                     unit.id, unit.success_rate, threshold)

    def _has_similar_unit(self, trigger: str) -> bool:
        """简单去重：trigger 关键词重叠度 > 70% 视为重复"""
        trigger_words = set(trigger.lower().split())
        if len(trigger_words) < 2:
            return False
        for u in self.manifest.units:
            if u.status == UnitStatus.ARCHIVED:
                continue
            existing_words = set(u.trigger.lower().split())
            if not existing_words:
                continue
            overlap = len(trigger_words & existing_words)
            similarity = overlap / min(len(trigger_words), len(existing_words))
            if similarity > 0.7:
                return True
        return False

    def _persist(self) -> None:
        """写入磁盘"""
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.save(self.persist_path)
