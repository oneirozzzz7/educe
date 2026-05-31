"""
DeepForge SelfEvolver — 最小可行的自进化闭环

框架自主改善能力的起点。每N次交互自动：
1. 用弱模型变异当前最优seed
2. 用Judge对比新旧seed的回答质量
3. 新的赢了就替换，输了就丢弃

设计原则：
- 不需要强模型——弱模型自己变异、自己评估
- 不需要理解"为什么有效"——只做变异→评估→选择
- 成功率低没关系——1/10成功就是进化
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from dataclasses import dataclass, field


EVOLVER_LOG = Path(".deepforge/evolution/self_evolver.jsonl")


@dataclass
class EvolutionRound:
    generation: int = 0
    current_seed: str = ""
    candidate_seed: str = ""
    wins_current: int = 0
    wins_candidate: int = 0
    result: str = ""
    timestamp: float = 0


class SelfEvolver:
    def __init__(self, client, model: str, initial_seed: str):
        self._client = client
        self._model = model
        self.current_best = initial_seed
        self._generation = 0
        self._call_count = 0
        self._candidate = None
        self._ab_results = []
        self._eval_attempts = 0
        self._max_eval_attempts = 20
        self._load_persisted_state()
        EVOLVER_LOG.parent.mkdir(parents=True, exist_ok=True)

    @property
    def evolving(self) -> bool:
        return self._candidate is not None

    def get_seed(self) -> str:
        return self.current_best

    def tick(self):
        self._call_count += 1
        if self.evolving:
            self._eval_attempts += 1
            if self._eval_attempts > self._max_eval_attempts and not self.ab_complete():
                self._candidate = None
                self._ab_results = []
                self._eval_attempts = 0

    def should_start_evolution(self) -> bool:
        return (not self.evolving
                and self._call_count > 0
                and self._call_count % 50 == 0)

    async def generate_candidate(self):
        try:
            result = await self._client.chat(
                messages=[
                    {"role": "system", "content": "你是一个prompt优化器。"},
                    {"role": "user", "content":
                     "请对以下激发语做一个微小但有意义的修改。"
                     "不要只替换同义词，要尝试改变某个具体的指令或结构。"
                     "只输出修改后的版本，不要解释。\n\n原始：" + self.current_best},
                ],
                model=self._model,
                max_tokens=100,
                temperature=0.9,
            )
            self._candidate = result.strip().strip('"').strip()
            self._ab_results = []
        except Exception:
            self._candidate = None

    async def evaluate_pair(self, question: str, response_current: str,
                            response_candidate: str):
        if not self._candidate:
            return

        from deepforge.core.judge import judge_response
        try:
            score_cur = await judge_response(
                self._client, self._model, question, response_current)
            score_cand = await judge_response(
                self._client, self._model, question, response_candidate)

            winner = "candidate" if score_cand.total > score_cur.total else "current" if score_cur.total > score_cand.total else "tie"
            self._ab_results.append({
                "question": question[:50],
                "current_score": score_cur.total,
                "candidate_score": score_cand.total,
                "winner": winner,
            })
        except Exception:
            pass

    def ab_complete(self) -> bool:
        return len(self._ab_results) >= 10

    def finalize(self) -> dict:
        if not self._ab_results:
            self._candidate = None
            return {"result": "no_data"}

        wins_cand = sum(1 for r in self._ab_results if r["winner"] == "candidate")
        wins_cur = sum(1 for r in self._ab_results if r["winner"] == "current")

        self._generation += 1

        if wins_cand >= 7:
            old = self.current_best
            self.current_best = self._candidate
            result = "evolved"
        else:
            result = "kept"

        record = {
            "timestamp": time.time(),
            "generation": self._generation,
            "result": result,
            "wins_candidate": wins_cand,
            "wins_current": wins_cur,
            "ties": len(self._ab_results) - wins_cand - wins_cur,
            "candidate": (self._candidate or "")[:80],
            "current": self.current_best[:80],
        }

        with open(EVOLVER_LOG, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._candidate = None
        self._ab_results = []
        self._eval_attempts = 0

        self._save_state()
        return record

    def get_stats(self) -> dict:
        return {
            "generation": self._generation,
            "call_count": self._call_count,
            "evolving": self.evolving,
            "ab_progress": len(self._ab_results) if self.evolving else 0,
            "current_seed": self.current_best[:60],
        }

    def _save_state(self):
        state_path = EVOLVER_LOG.parent / "self_evolver_state.json"
        state = {
            "generation": self._generation,
            "call_count": self._call_count,
            "current_best": self.current_best,
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))

    def _load_persisted_state(self):
        state_path = EVOLVER_LOG.parent / "self_evolver_state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                self._generation = state.get("generation", 0)
                self._call_count = state.get("call_count", 0)
                saved_seed = state.get("current_best", "")
                if saved_seed:
                    self.current_best = saved_seed
            except Exception:
                pass
