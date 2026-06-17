"""
DeepForge CredibilityEngine
四信号融合可信度体系——不是标注，是系统工程。

信号源及权重（随时间自校准）：
1. 模型自评：✅⚠️标注（权重低——模型不知道自己不知道什么）
2. 框架历史：同类问题过去的用户满意率（权重随数据量增加）
3. 知识验证：回答中的事实是否与已验证知识库匹配（权重高）
4. 用户反馈：点赞/踩/追问/说不对（权重最高，但数据最少）

随时间演进：
- 第1天：只有模型自评
- 第30天：框架历史有统计意义
- 第90天：知识库够大，能做知识验证
- 第180天：用户反馈足够，校准其他信号权重
"""
from __future__ import annotations

import re
import json
import time
from pathlib import Path


CREDIBILITY_DIR = Path(".educe/credibility")


class CredibilityEngine:
    def __init__(self, knowledge=None, quality_tracker=None):
        CREDIBILITY_DIR.mkdir(parents=True, exist_ok=True)
        self.knowledge = knowledge
        self.quality_tracker = quality_tracker
        self._feedback_log = CREDIBILITY_DIR / "feedback_log.jsonl"

    def assess(self, question: str, response: str, domain: str,
               user_signal: str = "neutral") -> dict:
        scores = {}

        # Signal 1: 模型自评（从回答中提取✅⚠️标注）
        scores["model_self"] = self._assess_model_self(response)

        # Signal 2: 框架历史（同领域历史满意率）
        scores["history"] = self._assess_history(domain)

        # Signal 3: 知识验证（事实与知识库匹配）
        scores["knowledge"] = self._assess_knowledge(question, response, domain)

        # Signal 4: 用户反馈
        scores["user_feedback"] = self._assess_user_feedback(user_signal)

        # 动态权重（根据数据量自适应）
        weights = self._compute_weights(domain)
        composite = sum(scores[k] * weights[k] for k in scores)

        return {
            "composite": round(composite, 3),
            "signals": scores,
            "weights": weights,
            "level": "high" if composite > 0.7 else "medium" if composite > 0.4 else "low",
        }

    def _assess_model_self(self, response: str) -> float:
        high_markers = len(re.findall(r'✅', response))
        low_markers = len(re.findall(r'⚠️|⚠', response))
        total = high_markers + low_markers
        if total == 0:
            return 0.5
        return round(high_markers / total, 2)

    def _assess_history(self, domain: str) -> float:
        if not self.quality_tracker:
            return 0.5
        stats = self.quality_tracker.get_domain_stats()
        domain_stat = stats.get(domain)
        if not domain_stat:
            return 0.5
        avg_q = domain_stat.get("avg_quality", 0.5)
        return min(1.0, max(0.0, avg_q))

    def _assess_knowledge(self, question: str, response: str, domain: str) -> float:
        if not self.knowledge:
            return 0.5

        recalled = self.knowledge.recall(question, max_results=5)
        if not recalled:
            return 0.5

        fact_entries = [r for r in recalled if r.startswith("[{}]".format(domain))]
        if not fact_entries:
            return 0.5

        matches = 0
        for fact in fact_entries:
            fact_text = fact.split("] ", 1)[-1] if "] " in fact else fact
            key_tokens = set(re.findall(r'[一-鿿]{2,}', fact_text))
            resp_tokens = set(re.findall(r'[一-鿿]{2,}', response))
            if key_tokens and len(key_tokens & resp_tokens) / len(key_tokens) > 0.3:
                matches += 1

        return min(1.0, 0.5 + matches * 0.2)

    def _assess_user_feedback(self, signal: str) -> float:
        signal_map = {
            "grateful": 0.9,
            "engaged": 0.7,
            "neutral": 0.5,
            "topic_switch": 0.4,
            "unsatisfied": 0.2,
            "error": 0.1,
            "unknown": 0.5,
        }
        return signal_map.get(signal, 0.5)

    def _compute_weights(self, domain: str) -> dict:
        has_history = False
        has_knowledge = False

        if self.quality_tracker:
            stats = self.quality_tracker.get_domain_stats()
            domain_stat = stats.get(domain, {})
            has_history = domain_stat.get("total_responses", 0) >= 10

        if self.knowledge:
            kb_stats = self.knowledge.stats()
            has_knowledge = kb_stats.get("total", 0) >= 20

        if has_history and has_knowledge:
            return {"model_self": 0.1, "history": 0.3, "knowledge": 0.3, "user_feedback": 0.3}
        elif has_history:
            return {"model_self": 0.15, "history": 0.35, "knowledge": 0.1, "user_feedback": 0.4}
        else:
            return {"model_self": 0.3, "history": 0.1, "knowledge": 0.1, "user_feedback": 0.5}

    def record_feedback(self, session_id: str, question: str, feedback: str):
        record = {
            "timestamp": time.time(),
            "session_id": session_id,
            "question": question[:100],
            "feedback": feedback,
        }
        with open(self._feedback_log, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
