"""
DeepForge KnowledgeDistiller
精准知识蒸馏——只提取事实性知识，按领域分类，质量门控。

Phase 0教训：
- 简单提取"含分析性表达的句子"效果为-0.08（噪声大于信号）
- 原因：观点和分析不是知识，注入后反而干扰模型思考

新策略：
- 只提取事实性陈述（含数字、定义、因果关系的确定性表述）
- 过滤掉观点、建议、模糊表述
- 按领域分类存储
- 只从positive/engaged信号的回答中提取
- 召回时按领域+触发词双重匹配
"""
from __future__ import annotations

import re
from typing import Optional


FACT_PATTERNS = re.compile(
    r"(?:^|\n)\s*(?:✅|[•\-\d]+[.、])\s*(.{15,120})"
)

DEFINITIVE_MARKERS = re.compile(
    r"\d+[%度℃万亿元年月日]|等于|即|是指|定义为|本质是|"
    r"公式|定理|定律|原理|机制|分为|包括|由.*组成"
)

OPINION_MARKERS = re.compile(
    r"我认为|我觉得|可能|大概|也许|似乎|或许|据说|"
    r"建议|推荐|可以尝试|不妨|考虑"
)


class KnowledgeDistiller:
    def __init__(self, knowledge_cache):
        self.knowledge = knowledge_cache

    def distill(self, question: str, response: str, domain: str,
                user_signal: str = "neutral") -> list:
        if user_signal in ("error", "unsatisfied"):
            return []

        if len(response) < 100:
            return []

        facts = self._extract_facts(response)
        if not facts:
            return []

        stored = []
        for fact in facts[:3]:
            triggers = self.knowledge._tokenize(question + " " + domain + " " + fact)
            entry_id = self.knowledge.add(
                "[{}] {}".format(domain, fact),
                triggers, category="fact"
            )
            stored.append({"domain": domain, "fact": fact, "id": entry_id})

        return stored

    def _extract_facts(self, response: str) -> list:
        candidates = []

        sentences = re.split(r'[。\n]', response)
        for s in sentences:
            s = s.strip().lstrip("- •·")
            s = re.sub(r'^[✅⚠️]\s*\d*%?\s*', '', s).strip()

            if len(s) < 15 or len(s) > 150:
                continue

            if OPINION_MARKERS.search(s):
                continue

            if DEFINITIVE_MARKERS.search(s):
                candidates.append(s)

        return candidates

    def recall_for_domain(self, query: str, domain: str, max_results: int = 3) -> list:
        all_recalled = self.knowledge.recall(query, max_results=max_results * 2)
        domain_filtered = []
        for item in all_recalled:
            if item.startswith("[{}]".format(domain)):
                domain_filtered.append(item)
            if len(domain_filtered) >= max_results:
                break
        return domain_filtered
