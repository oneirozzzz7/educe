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

ACTIVATION_PROMPT = """你是DeepForge智能助手。当用户问你是谁时，回答"我是DeepForge智能助手"。

请根据问题的实际需要，自行决定回答的深度和结构：

- 简单问题（如问好、简单计算）：直接回答，不要过度展开
- 需要分析的问题：按以下框架组织回答

## 回答框架（根据需要选用）

**领域识别**：先判断问题属于什么领域

**结构化分析**：根据领域选择合适的推理方式
{reasoning_chains}

**置信度标注**：在每个关键结论后面标注可信度：
- 高可信用 ✅ 加百分比，如 ✅92%
- 需验证用 ⚠️ 加百分比，如 ⚠️75%
例如："北宋定都开封 ✅95%"、"欧阳修（1007-1072年）⚠️80%"
每个重要事实都要标注。百分比要基于你对该事实的确信程度。

## 规则
- 你自己判断问题需要多深入的回答——不要对简单问题过度展开，也不要对复杂问题敷衍
- 不确定就说不确定，绝不编造
- 使用准确术语但辅以通俗解释
- 涉及医学、法律、金融，末尾提醒用户咨询专业人士
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
    """LLM能力激发引擎——通过prompt结构激活模型深层知识"""

    def __init__(self, knowledge=None, domain_engine=None):
        self.knowledge = knowledge
        self.domain_engine = domain_engine

    def build_activation_prompt(self, user_input: str,
                                 domain_context: str = "",
                                 l1_compiled: list[str] | None = None) -> str:
        """生成激发prompt——稀疏路由，只注入相关领域的推理链"""
        extra_parts = []
        if domain_context:
            extra_parts.append(domain_context)
        if l1_compiled:
            extra_parts.append("\n## 已验证的知识\n" + "\n".join(f"- {k}" for k in l1_compiled[:5]))

        extra_context = "\n".join(extra_parts)

        from deepforge.core.domain_router import route_domain
        domains = route_domain(user_input, top_k=2)
        chains_text = self._format_selected_chains(domains)

        return ACTIVATION_PROMPT.format(
            reasoning_chains=chains_text,
            extra_context=extra_context,
        )

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
