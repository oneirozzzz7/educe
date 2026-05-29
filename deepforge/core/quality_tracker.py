"""
DeepForge 质量追踪器
收集用户行为信号 + 回答特征 → 聚合领域统计 → 发现薄弱领域 → 驱动激发语演化

信号收集原则：
- 普通用户完全无感知（被动提取行为信号）
- 深度用户偶尔主动问（克制、不打扰）
- 回答本身也是信号源（闭合度、结构、置信度）
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from dataclasses import dataclass, asdict


FEEDBACK_DIR = Path(".deepforge/feedback")

NEGATIVE_PATTERNS = re.compile(r"不对|错了|不是这样|不准确|重新|再说一遍|你说错了|回答有误")
POSITIVE_PATTERNS = re.compile(r"谢谢|感谢|太好了|不错|很棒|有帮助|学到了|明白了|懂了|👍")
CONTINUE_PATTERNS = re.compile(
    r"这个|这篇|这段|上面|上文|刚才|继续|接着|详细|展开|深入|更多|举例|为什么这样|怎么理解|"
    r"那么|所以|也就是说|具体来说"
)


@dataclass
class QualityRecord:
    timestamp: float
    question: str
    domain: str
    seed_variant: str
    response_len: int
    depth_score: float
    structure_score: float
    confidence_coverage: float
    closure_score: float
    user_signal: str
    user_signal_weight: float
    composite_quality: float
    model: str


class QualityTracker:
    """质量追踪——记录、聚合、分析、发现"""

    def __init__(self):
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        self._log_path = FEEDBACK_DIR / "quality_log.jsonl"
        self._stats_path = FEEDBACK_DIR / "domain_stats.json"
        self._response_count = 0

    def record(self, question: str, domain: str, seed: str, response: str,
               user_signal: str = "unknown", signal_weight: float = 0.0,
               model: str = ""):
        """记录一次回答的质量数据"""
        features = self._extract_features(response)

        if user_signal != "unknown" and signal_weight != 0:
            composite = signal_weight * 0.6 + features["avg"] * 0.4
        else:
            composite = features["avg"]

        record = QualityRecord(
            timestamp=time.time(),
            question=question[:100],
            domain=domain,
            seed_variant=seed[:60],
            response_len=len(response),
            depth_score=features["depth"],
            structure_score=features["structure"],
            confidence_coverage=features["confidence"],
            closure_score=features["closure"],
            user_signal=user_signal,
            user_signal_weight=signal_weight,
            composite_quality=round(composite, 3),
            model=model,
        )

        with open(self._log_path, "a") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

        self._response_count += 1
        if self._response_count % 10 == 0:
            self.aggregate()

    def detect_user_signal(self, current_input: str, previous_assistant: str = "") -> tuple[str, float]:
        """从用户当前输入推断对上一轮回答的反馈"""
        if not previous_assistant:
            return "unknown", 0.0

        if NEGATIVE_PATTERNS.search(current_input):
            return "error", -0.8

        if POSITIVE_PATTERNS.search(current_input):
            return "grateful", 0.5

        if CONTINUE_PATTERNS.search(current_input):
            return "engaged", 0.3

        prev_tokens = set(re.findall(r'[一-鿿]{2,}', previous_assistant))
        curr_tokens = set(re.findall(r'[一-鿿]{2,}', current_input))
        if prev_tokens and curr_tokens:
            overlap = len(prev_tokens & curr_tokens) / max(len(curr_tokens), 1)
            if overlap > 0.3:
                return "unsatisfied", -0.5

        return "topic_switch", 0.1

    def aggregate(self):
        """聚合质量日志为领域统计"""
        if not self._log_path.exists():
            return

        domain_data: dict[str, list[dict]] = {}
        with open(self._log_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    d = r.get("domain", "通用")
                    if d not in domain_data:
                        domain_data[d] = []
                    domain_data[d].append(r)
                except Exception:
                    pass

        stats = {}
        all_qualities = []
        for domain, records in domain_data.items():
            qualities = [r["composite_quality"] for r in records]
            all_qualities.extend(qualities)
            depths = [r["depth_score"] for r in records]
            stats[domain] = {
                "total_responses": len(records),
                "avg_quality": round(sum(qualities) / len(qualities), 3),
                "avg_depth": round(sum(depths) / len(depths), 3),
                "best_seed": max(records, key=lambda r: r["composite_quality"])["seed_variant"],
                "best_seed_quality": max(r["composite_quality"] for r in records),
                "last_updated": time.time(),
            }

        global_avg = sum(all_qualities) / max(len(all_qualities), 1)
        for domain, s in stats.items():
            s["needs_improvement"] = s["avg_quality"] < global_avg - 0.05

        self._stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2))

    def get_domain_stats(self) -> dict:
        """读取领域统计"""
        if self._stats_path.exists():
            return json.loads(self._stats_path.read_text())
        return {}

    def get_weak_domains(self) -> list[str]:
        """获取薄弱领域列表"""
        stats = self.get_domain_stats()
        return [d for d, s in stats.items() if s.get("needs_improvement")]

    def _extract_features(self, response: str) -> dict:
        """从回答文本提取质量特征——注重内容实质而非格式"""
        if not response or len(response) < 20:
            return {"depth": 0, "structure": 0, "confidence": 0, "closure": 0, "avg": 0}

        # 深度：分析性表达+举例+推理链（不只数关键词）
        depth_words = len(re.findall(
            r'因为|本质|核心|原理|根本|关键|深层|实质|背后|底层|'
            r'具体来说|换句话说|值得注意|区别在于|原因在于',
            response
        ))
        has_examples = bool(re.search(r'例如|比如|举个例子|比方说|以.*为例', response))
        has_reasoning = bool(re.search(r'所以|因此|由此可见|这意味着|导致|进而', response))
        depth = min((depth_words * 0.1 + (0.25 if has_examples else 0) + (0.25 if has_reasoning else 0)), 1.0)

        # 结构：不要求特定格式，看是否有层次
        paragraphs = response.count('\n\n')
        has_any_org = paragraphs >= 2 or bool(re.search(r'(?:^|\n)\s*\d+[.、]', response))
        length_ok = len(response) > 200
        structure = (0.4 if has_any_org else 0.15) + (0.3 if length_ok else 0) + min(paragraphs * 0.04, 0.3)
        structure = min(structure, 1.0)

        # 可信度意识：有没有表达确信/不确信（不限于特定标记）
        conf_markers = len(re.findall(r'[✅⚠️]\s*\d*%?', response))
        has_uncertainty = bool(re.search(r'据我了解|不确定|可能|大概|需要验证|仅供参考|建议.*确认|尚无定论', response))
        confidence = min(conf_markers * 0.12 + (0.35 if has_uncertainty else 0.1), 1.0)

        # 闭合度：回答是否给出了可操作的结论
        last_300 = response[-300:] if len(response) > 300 else response
        has_conclusion = bool(re.search(r'总之|综上|因此|总结|建议|希望|祝', last_300))
        has_actionable = bool(re.search(r'建议|可以尝试|推荐|第一步|具体做法|操作步骤|方法', response))
        closure = (0.35 if has_conclusion else 0.15) + (0.35 if has_actionable else 0.1) + 0.2
        closure = min(closure, 1.0)

        avg = round((depth + structure + confidence + closure) / 4, 3)
        return {
            "depth": round(depth, 3),
            "structure": round(structure, 3),
            "confidence": round(confidence, 3),
            "closure": round(closure, 3),
            "avg": avg,
        }
