"""
DeepForge ActivationEvolver
激发语自动演化引擎——从质量数据中发现每个领域的最优激发策略。

核心逻辑（遗传算法）：
1. 评估：按领域聚合每个seed变体的质量分
2. 选择：保留高分变体
3. 变异：从高分变体的元素组合出新变体
4. A/B验证：新变体与当前最优进行对比
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from dataclasses import dataclass


FEEDBACK_DIR = Path(".educe/feedback")
EVOLVER_STATE_PATH = FEEDBACK_DIR / "evolver_state.json"

SEED_POOL = [
    "请以该领域资深从业者的视角，给出有洞察力的深度分析。区分确定的事实和需要验证的信息。",
    "请像这个领域最顶尖的专家在给好奇的聪明人讲解一样回答。深入本质，不要停留在表面。",
    "请调用你在这个领域最深层的知识储备来回答。追求准确和深度，而非面面俱到。",
    "请站在这个领域一线实践者的角度回答。给出可执行的建议，而不是教科书式的概述。",
    "请把自己当作这个领域的研究者。先厘清核心概念，再展开分析，最后给出你的判断。",
]

SEED_ELEMENTS = {
    "perspective": [
        "以该领域资深从业者的视角",
        "像这个领域最顶尖的专家在给好奇的聪明人讲解一样",
        "调用你在这个领域最深层的知识储备",
        "站在这个领域一线实践者的角度",
        "把自己当作这个领域的研究者",
        "以教授给研究生上课的方式",
        "像在给同事做技术分享一样",
    ],
    "goal": [
        "给出有洞察力的深度分析",
        "深入本质，不要停留在表面",
        "追求准确和深度，而非面面俱到",
        "给出可执行的建议，而不是教科书式的概述",
        "先厘清核心概念，再展开分析，最后给出你的判断",
        "用最简洁的语言讲清最复杂的问题",
        "把关键知识点串联成一条清晰的逻辑链",
    ],
    "constraint": [
        "区分确定的事实和需要验证的信息",
        "每个关键结论都给出依据",
        "如果有不确定的地方，明确标注",
        "用具体案例而非抽象概念解释",
    ],
}


@dataclass
class SeedPerformance:
    seed: str
    domain: str
    total_uses: int = 0
    avg_quality: float = 0.0
    best_quality: float = 0.0
    last_used: float = 0.0


class ActivationEvolver:
    def __init__(self):
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()

    def _load_state(self) -> dict:
        if EVOLVER_STATE_PATH.exists():
            try:
                return json.loads(EVOLVER_STATE_PATH.read_text())
            except Exception:
                pass
        return {
            "domain_best_seeds": {},
            "seed_pool": SEED_POOL[:],
            "generation": 0,
            "last_evolved": 0,
            "ab_candidates": {},
        }

    def _save_state(self):
        EVOLVER_STATE_PATH.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2)
        )

    def get_best_seed(self, domain: str = "") -> str:
        ab = self._state.get("ab_candidates", {}).get(domain)
        if ab and ab.get("uses", 0) < ab.get("target_uses", 5):
            ab["uses"] = ab.get("uses", 0) + 1
            self._save_state()
            return ab["seed"]

        if domain and domain in self._state.get("domain_best_seeds", {}):
            return self._state["domain_best_seeds"][domain]
        return SEED_POOL[1]

    def analyze_and_evolve(self) -> dict:
        log_path = FEEDBACK_DIR / "quality_log.jsonl"
        if not log_path.exists():
            return {"status": "no_data"}

        records = []
        with open(log_path) as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

        if len(records) < 10:
            return {"status": "insufficient_data", "count": len(records)}

        domain_seed_stats = {}
        for r in records:
            domain = r.get("domain", "general")
            seed = r.get("seed_variant", "")[:60]
            quality = r.get("composite_quality", 0)

            key = (domain, seed)
            if key not in domain_seed_stats:
                domain_seed_stats[key] = {
                    "count": 0, "total_quality": 0, "best": 0
                }
            stats = domain_seed_stats[key]
            stats["count"] += 1
            stats["total_quality"] += quality
            stats["best"] = max(stats["best"], quality)

        # 选择：每个领域的最优seed
        domain_best = {}
        for (domain, seed), stats in domain_seed_stats.items():
            if stats["count"] < 2:
                continue
            avg = stats["total_quality"] / stats["count"]
            if domain not in domain_best or avg > domain_best[domain]["avg"]:
                domain_best[domain] = {
                    "seed": seed,
                    "avg": round(avg, 3),
                    "count": stats["count"],
                    "best": round(stats["best"], 3),
                }

        for domain, info in domain_best.items():
            full_seed = self._find_full_seed(info["seed"])
            if full_seed:
                self._state["domain_best_seeds"][domain] = full_seed

        # 变异：为薄弱领域生成新变体
        weak_domains = self._find_weak_domains(domain_best)
        new_variants = self._mutate(weak_domains)

        # A/B：把新变体注册为候选
        for domain, variant in new_variants.items():
            if variant not in self._state.get("seed_pool", []):
                self._state.setdefault("seed_pool", []).append(variant)
            self._state.setdefault("ab_candidates", {})[domain] = {
                "seed": variant,
                "uses": 0,
                "target_uses": 5,
                "created_at": time.time(),
            }

        self._state["generation"] += 1
        self._state["last_evolved"] = time.time()
        self._save_state()

        return {
            "status": "evolved",
            "generation": self._state["generation"],
            "domain_best": domain_best,
            "domains_optimized": len(domain_best),
            "mutations": len(new_variants),
            "weak_domains": weak_domains,
        }

    def _find_weak_domains(self, domain_best: dict) -> list:
        if not domain_best:
            return []
        avg_all = sum(d["avg"] for d in domain_best.values()) / len(domain_best)
        return [d for d, info in domain_best.items() if info["avg"] < avg_all - 0.05]

    def _mutate(self, weak_domains: list) -> dict:
        rng = random.Random(int(time.time()))
        new_variants = {}
        for domain in weak_domains[:3]:
            perspective = rng.choice(SEED_ELEMENTS["perspective"])
            goal = rng.choice(SEED_ELEMENTS["goal"])
            constraint = rng.choice(SEED_ELEMENTS["constraint"])
            variant = "请{}，{}。{}。".format(perspective, goal, constraint)
            new_variants[domain] = variant
        return new_variants

    def _find_full_seed(self, seed_prefix: str) -> str:
        for seed in self._state.get("seed_pool", SEED_POOL):
            if seed[:60] == seed_prefix:
                return seed
        for seed in SEED_POOL:
            if seed[:60] == seed_prefix:
                return seed
        return ""

    def get_stats(self) -> dict:
        return {
            "generation": self._state.get("generation", 0),
            "domains_optimized": len(self._state.get("domain_best_seeds", {})),
            "seed_pool_size": len(self._state.get("seed_pool", [])),
            "last_evolved": self._state.get("last_evolved", 0),
            "ab_active": len(self._state.get("ab_candidates", {})),
        }
