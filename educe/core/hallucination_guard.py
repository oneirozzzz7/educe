"""
DeepForge 反幻觉审计层 v2
不是让模型审计自己（狐狸看鸡窝），而是用结构化规则+模型辅助双层检查

策略：
1. 规则层（零成本）：检测高危模式——编造数据、虚假引用、危险建议
2. 标注层（轻量LLM）：仅对检测到高危信号的回答做标注，不重写
"""
from __future__ import annotations

import re
from typing import Any
import logging

log = logging.getLogger("educe.core.hallucination_guard")

SENSITIVE_DOMAINS = {
    "medical": ["症状", "诊断", "治疗", "用药", "剂量", "手术", "病", "癌", "药物", "处方", "服用"],
    "legal": ["法律", "诉讼", "判决", "合同", "赔偿", "违法", "刑事", "民事", "起诉", "律师"],
    "financial": ["投资", "理财", "股票", "基金", "保险", "贷款", "利率", "收益率", "回报", "风险"],
}

DISCLAIMER = {
    "medical": "\n\n💡 以上为AI参考信息，医疗相关决策请咨询专业医生。",
    "legal": "\n\n💡 以上为AI参考信息，法律问题请咨询专业律师。",
    "financial": "\n\n💡 以上为AI参考信息，投资有风险，请咨询专业理财顾问。",
}

FABRICATION_PATTERNS = [
    (r'据\d{4}年.*?(?:研究|报告|数据|统计)', "引用了具体年份的研究/数据"),
    (r'(?:根据|来自).*?(?:大学|研究院|机构).*?(?:研究|报告)', "引用了具体机构"),
    (r'\d{1,3}(?:\.\d+)?%的(?:人|用户|研究|数据)', "引用了具体百分比数据"),
    (r'(?:已被|经过).*?(?:证实|证明|验证)', "使用了断言性语言"),
]

AUDIT_PROMPT = """请检查以下回答中是否有明显不准确的地方。
不要重写回答，只列出你认为可能不准确的部分（如果有的话）。
如果回答整体可靠，直接回复"PASS"。

回答内容：
{response}

格式：
- PASS（如果没问题）
- 或列出可疑点：1. "具体内容" - 原因"""


async def audit_response(question: str, response: str, model_client: Any,
                         model: str, max_tokens: int = 4096,
                         mode: str = "quick") -> str:
    if not response or len(response) < 50:
        return response

    if _is_pure_code(response):
        return response

    if _is_casual(response):
        return response

    result = response

    sensitive = _detect_sensitive_domain(response)
    if sensitive:
        result = result.rstrip() + DISCLAIMER[sensitive]

    fabrications = _detect_fabrication(response)
    if fabrications:
        warnings = "；".join(fabrications[:3])
        result = f"【⚠️ 以下回答中部分信息（{warnings}）可能需要验证】\n\n" + result

    if mode == "deep" and (fabrications or sensitive):
        try:
            audit = await _llm_spot_check(response, model_client, model, max_tokens)
            if audit and audit != "PASS":
                result = result.rstrip() + f"\n\n---\n📋 **AI自查备注**：{audit}"
        except Exception as e:
            log.debug("suppressed: %s", e)

    return result


def _detect_sensitive_domain(text: str) -> str | None:
    """检测是否涉及敏感领域"""
    for domain, keywords in SENSITIVE_DOMAINS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits >= 2:
            return domain
    return None


def _detect_fabrication(text: str) -> list[str]:
    """检测可能编造的内容"""
    found = []
    for pattern, desc in FABRICATION_PATTERNS:
        if re.search(pattern, text):
            found.append(desc)
    return found


def _is_pure_code(response: str) -> bool:
    """纯代码输出不需要审计"""
    code_ratio = len(re.findall(r'```[\s\S]*?```', response))
    text_lines = [l for l in response.split('\n') if l.strip() and not l.strip().startswith('```')]
    if not text_lines:
        return True
    if "```filepath:" in response or "<!DOCTYPE" in response:
        return True
    return False


def _is_casual(response: str) -> bool:
    """闲聊不需要审计"""
    if len(response) < 100:
        casual_patterns = ["你好", "好的", "没问题", "不客气", "谢谢", "很高兴", "有什么可以帮"]
        return any(p in response for p in casual_patterns)
    return False


async def _llm_spot_check(response: str, model_client: Any,
                          model: str, max_tokens: int) -> str:
    """LLM抽查——不重写，只指出可疑点"""
    prompt = AUDIT_PROMPT.format(response=response[:3000])
    result = await model_client.chat(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=512,
        temperature=0.1,
    )
    if not result or len(result) < 3:
        return "PASS"
    return result.strip()[:500]
