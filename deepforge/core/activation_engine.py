"""
DeepForge LLM 能力激发引擎
核心理念：不是告诉模型"你是X专家"，而是通过 prompt 结构激发模型预训练知识中的深层能力

5层激发：
  1. 领域自识别 — 模型自己判断领域（激活对应知识区域）
  2. 知识检索 — 强制列出关键事实（显式检索减少幻觉）
  3. 结构化推理 — 按领域推理链展开
  4. 置信度自检 — 内置反幻觉
  5. 专家补充 — 检查遗漏和前沿进展
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


REASONING_CHAINS = {
    "medical": "症状描述 → 可能原因（从常见到罕见） → 建议检查 → 就医建议",
    "legal": "事实认定 → 适用法条 → 法律分析 → 实操建议 → 时效提醒",
    "math": "已知条件 → 求解目标 → 选择方法 → 逐步推导 → 验证结果",
    "tech": "问题定位 → 原理分析 → 解决方案（含权衡） → 最佳实践",
    "finance": "背景分析 → 风险评估 → 方案对比 → 注意事项",
    "writing": "体裁与读者 → 结构规划 → 内容展开 → 语言润色",
    "psychology": "共情回应 → 感受确认 → 原因分析 → 具体建议 → 专业资源",
    "history": "时代背景 → 关键事件 → 因果分析 → 多角度评价 → 历史影响",
    "science": "核心概念 → 原理解释 → 通俗类比 → 前沿进展 → 开放问题",
    "cooking": "食材准备（精确用量） → 关键步骤 → 火候时间 → 常见失误 → 提升技巧",
    "education": "学习困难诊断 → 认知科学策略 → 具体计划 → 执行建议",
    "general": "背景梳理 → 核心分析 → 结论 → 延伸建议",
}

DOMAIN_LABELS = {
    "medical": "医学", "legal": "法律", "math": "数学",
    "tech": "技术", "finance": "金融", "writing": "写作",
    "psychology": "心理", "history": "历史", "science": "科学",
    "cooking": "烹饪", "education": "教育",
}

# ═══════════════════════════════════════
# 激发语——可演化的核心
# 存储在知识库中，随使用效果动态调整
# ═══════════════════════════════════════

DEFAULT_ACTIVATION_SEED = "请以该领域资深从业者的视角，给出有洞察力的深度分析。区分确定的事实和需要验证的信息。"

ACTIVATION_PROMPT = """你是代号E，Educe智能助手。当用户问你是谁时，回答"我是代号E，你的智能助手，帮你把想法变成现实"。

{activation_seed}

回答要求：
- 专注回答用户最新的问题，对话历史中可能有不同话题，不要混淆
- 对确定的事实标注 ✅，不完全确定的标注 ⚠️
- 涉及计算时展示推理步骤并验证结果
- 涉及医学、法律、金融，提醒咨询专业人士
- 末尾注明"以上分析仅供参考，具体情况请结合实际判断"
{extra_context}"""


@dataclass
class ConfidenceItem:
    claim: str
    level: str  # "high", "medium", "low"
    reason: str = ""


@dataclass
class ActivatedResponse:
    domain: str = ""
    key_knowledge: list[str] = field(default_factory=list)
    main_answer: str = ""
    confidence_items: list[ConfidenceItem] = field(default_factory=list)
    expert_supplement: str = ""
    low_confidence_claims: list[str] = field(default_factory=list)
    overall_confidence: str = "medium"
    raw_response: str = ""


class ActivationEngine:
    """LLM能力激发引擎——用最少的prompt触发模型最深的思考

    核心机制：
    1. 激发语(activation_seed)——一句话激活模型深度思考模式
    2. 激发语可演化——存储在知识库，根据效果数据自动优化
    3. 不依赖推理链模板——让模型自己选择最佳推理方式（涌现）
    """

    SEED_VARIANTS = [
        "请像这个领域最顶尖的专家在给好奇的聪明人讲解一样回答。深入本质，不要停留在表面。",
        "请以该领域资深从业者的视角，给出有洞察力的深度分析。区分确定的事实和需要验证的信息。",
        "请调用你在这个领域最深层的知识储备来回答。追求准确和深度，而非面面俱到。",
    ]

    def __init__(self, knowledge=None, domain_engine=None):
        self.knowledge = knowledge
        self.domain_engine = domain_engine
        self._current_seed = self._load_best_seed()
        self._use_count = 0
        self._evolver = None
        try:
            from deepforge.core.activation_evolver import ActivationEvolver
            self._evolver = ActivationEvolver()
        except Exception:
            pass

    def _load_best_seed(self) -> str:
        """从领域统计中加载效果最好的激发语"""
        try:
            from deepforge.core.quality_tracker import QualityTracker
            tracker = QualityTracker()
            stats = tracker.get_domain_stats()
            if stats:
                # 找所有领域中best_seed_quality最高的seed
                best_seed = None
                best_quality = 0
                for domain_stat in stats.values():
                    q = domain_stat.get("best_seed_quality", 0)
                    s = domain_stat.get("best_seed", "")
                    if q > best_quality and s:
                        best_quality = q
                        best_seed = s
                if best_seed and best_quality > 0.5:
                    return best_seed
        except Exception:
            pass
        return DEFAULT_ACTIVATION_SEED

    def build_activation_prompt(self, user_input: str,
                                 domain_context: str = "",
                                 l1_compiled: list[str] | None = None) -> str:
        """生成激发prompt——领域级最优seed + 薄弱领域自动补充"""
        extra_parts = []
        if domain_context:
            extra_parts.append(domain_context)
        if l1_compiled:
            extra_parts.append("\n## 已验证的知识\n" + "\n".join("- {}".format(k) for k in l1_compiled[:5]))

        domain_hint = self._get_domain_hint(user_input)
        if domain_hint:
            extra_parts.append(domain_hint)

        extra_context = "\n".join(extra_parts)

        # 领域级最优seed（如果evolver有数据）
        seed = self._current_seed
        if self._evolver:
            detected_domain = self._detect_domain_for_seed(user_input)
            domain_seed = self._evolver.get_best_seed(detected_domain)
            if domain_seed:
                seed = domain_seed

        return ACTIVATION_PROMPT.format(
            activation_seed=seed,
            extra_context=extra_context,
        )

    def _detect_domain_for_seed(self, user_input: str) -> str:
        try:
            from deepforge.core.domain_router import route_domain
            domains = route_domain(user_input, top_k=1)
            if domains:
                return DOMAIN_LABELS.get(domains[0], domains[0])
        except Exception:
            pass
        return ""

    def _get_domain_hint(self, user_input: str) -> str:
        """对薄弱领域自动补充提示——从成功回答中学习"""
        try:
            from deepforge.core.quality_tracker import QualityTracker
            tracker = QualityTracker()
            stats = tracker.get_domain_stats()
            if not stats:
                return ""

            from deepforge.core.domain_router import route_domain
            domains = route_domain(user_input, top_k=1)
            if not domains or domains[0] == "general":
                return ""

            domain_en = domains[0]
            domain_cn = DOMAIN_LABELS.get(domain_en, domain_en)
            domain_stat = stats.get(domain_cn) or stats.get(domain_en)

            if not domain_stat or not domain_stat.get("needs_improvement"):
                return ""

            # 从知识库找该领域的成功insight作为示范
            hint_parts = [f"\n（{domain_cn}领域需要特别注意深度和准确性）"]
            if self.knowledge:
                domain_insights = []
                for e in self.knowledge._entries.values():
                    if e.category == "insight" and domain_cn in e.content[:10]:
                        domain_insights.append(e.content[len(domain_cn)+3:80])
                if domain_insights:
                    hint_parts.append("参考此前的成功回答要点：" + "；".join(domain_insights[:2]))

            return "\n".join(hint_parts)
        except Exception:
            pass
        return ""

    def parse_activated_response(self, raw_response: str) -> ActivatedResponse:
        """从模型回复中解析结构化信息（best-effort，不丢失内容）"""
        result = ActivatedResponse(raw_response=raw_response, main_answer=raw_response)

        domain_match = re.search(r'【领域】[：:]\s*(.+?)(?:\n|$)', raw_response)
        if domain_match:
            result.domain = domain_match.group(1).strip()

        knowledge_match = re.search(r'【关键知识】[：:]?\s*([\s\S]*?)(?=\n(?:##|【)|$)', raw_response)
        if knowledge_match:
            items = re.findall(r'\d+[.、]\s*(.+)', knowledge_match.group(1))
            result.key_knowledge = [item.strip() for item in items if item.strip()]

        supplement_match = re.search(r'【专家补充】[：:]\s*([\s\S]*?)(?=\n【|$)', raw_response)
        if supplement_match:
            result.expert_supplement = supplement_match.group(1).strip()

        # 解析百分比置信度
        pct_matches = re.findall(r'置信度:\s*(\d+)%', raw_response)
        if not pct_matches:
            pct_matches = re.findall(r'模型自评:\s*(\d+)%', raw_response)
        if pct_matches:
            for pct_str in pct_matches:
                pct = int(pct_str)
                level = "high" if pct >= 90 else "medium" if pct >= 70 else "low"
                item = ConfidenceItem(claim=f"{pct}%", level=level)
                result.confidence_items.append(item)
                if level == "low":
                    result.low_confidence_claims.append(f"置信度{pct}%")

        # 兼容旧格式的emoji标注
        confidence_section = re.search(r'【置信度说明】[：:]?\s*([\s\S]*?)(?=\n【|$)', raw_response)
        if confidence_section:
            for line in confidence_section.group(1).split("\n"):
                line = line.strip().lstrip("- ")
                if "✅" in line:
                    result.confidence_items.append(ConfidenceItem(claim=line, level="high"))
                elif "⚠️" in line or "⚠" in line:
                    result.confidence_items.append(ConfidenceItem(claim=line, level="medium"))
                elif "❓" in line:
                    item = ConfidenceItem(claim=line, level="low")
                    result.confidence_items.append(item)
                    result.low_confidence_claims.append(line)

        if result.confidence_items:
            low = sum(1 for c in result.confidence_items if c.level == "low")
            high = sum(1 for c in result.confidence_items if c.level == "high")
            if low > 0:
                result.overall_confidence = "low"
            elif high == len(result.confidence_items):
                result.overall_confidence = "high"
            else:
                result.overall_confidence = "medium"

        return result

    def _estimate_complexity(self, user_input: str) -> str:
        """所有问题统一用moderate模板——不做不可靠的分级判断"""
        return "moderate"

    def _format_reasoning_chains(self) -> str:
        lines = []
        for domain, chain in REASONING_CHAINS.items():
            if domain == "general":
                lines.append(f"- 其他问题：{chain}")
            else:
                label = DOMAIN_LABELS.get(domain, domain)
                lines.append(f"- {label}问题：{chain}")
        return "\n".join(lines)

    def _format_selected_chains(self, domains: list[str]) -> str:
        """只注入选中领域的推理链——MoE稀疏激活"""
        lines = []
        for d in domains:
            if d in REASONING_CHAINS and d != "general":
                label = DOMAIN_LABELS.get(d, d)
                lines.append(f"- {label}问题：{REASONING_CHAINS[d]}")
        lines.append(f"- 其他问题：{REASONING_CHAINS['general']}")
        return "\n".join(lines)
