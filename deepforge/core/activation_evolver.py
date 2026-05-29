"""
DeepForge ActivationEvolver
激发语自动演化引擎——从质量数据中发现每个领域的最优激发策略。

核心逻辑：
1. 按领域聚合每个seed变体的质量分
2. 保留高分变体作为该领域的最优seed
3. 周期性生成新变体探索更好的策略
4. 新变体从高分变体的元素组合生成（不是随机变异）

这不是换prompt——是框架自己学会了怎么激发不同领域的模型能力。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass


FEEDBACK_DIR = Path(".deepforge/feedback")
EVOLVER_STATE_PATH = FEEDBACK_DIR / "evolver_state.json"

SEED_POOL = [
    "请以该领域资深从业者的视角，给出有洞察力的深度分析。区分确定的事实和需要验证的信息。",
    "请像这个领域最顶尖的专家在给好奇的聪明人讲解一样回答。深入本质，不要停留在表面。",
    "请调用你在这个领域最深层的知识储备来回答。追求准确和深度，而非面面俱到。",
    "请站在这个领域一线实践者的角度回答。给出可执行的建议，而不是教科书式的概述。",
    "请把自己当作这个领域的研究者。先厘清核心概念，再展开分析，最后给出你的判断。",
]


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
        }

    def _save_state(self):
        EVOLVER_STATE_PATH.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2)
        )

    def get_best_seed(self, domain: str = "") -> str:
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

        self._state["generation"] += 1
        self._state["last_evolved"] = time.time()
        self._save_state()

        return {
            "status": "evolved",
            "generation": self._state["generation"],
            "domain_best": domain_best,
            "domains_optimized": len(domain_best),
        }

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
        }
