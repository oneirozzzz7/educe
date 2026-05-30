"""
DeepForge 趋势追踪器
记录每次benchmark的结果，分析框架质量随时间的变化趋势。

回答核心问题："框架在变好还是变差？"
"""
from __future__ import annotations

import json
import time
import subprocess
from pathlib import Path
from datetime import datetime


BENCHMARKS_DIR = Path(".deepforge/benchmarks")


def record_benchmark(results: list, metadata: dict = None) -> Path:
    BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)

    git_hash = ""
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        pass

    record = {
        "timestamp": time.time(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "git_commit": git_hash,
        "results": results,
        "summary": {
            "total_questions": len(results),
            "avg_invariant": round(
                sum(r.get("invariant_score", 0) for r in results) / max(len(results), 1), 3),
            "avg_bonus": round(
                sum(r.get("bonus_score", 0) for r in results) / max(len(results), 1), 3),
            "anti_violations": sum(r.get("anti_violations", 0) for r in results),
        },
    }
    if metadata:
        record["metadata"] = metadata

    filename = "benchmark_{}.json".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
    path = BENCHMARKS_DIR / filename
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return path


def load_history() -> list:
    if not BENCHMARKS_DIR.exists():
        return []
    records = []
    for path in sorted(BENCHMARKS_DIR.glob("benchmark_*.json")):
        try:
            records.append(json.loads(path.read_text()))
        except Exception:
            pass
    return records


def analyze_trend(history: list = None) -> dict:
    if history is None:
        history = load_history()

    if len(history) < 2:
        return {"status": "insufficient_data", "records": len(history)}

    scores = [h["summary"]["avg_invariant"] for h in history]
    timestamps = [h["timestamp"] for h in history]

    recent_3 = scores[-3:] if len(scores) >= 3 else scores
    older_3 = scores[-6:-3] if len(scores) >= 6 else scores[:len(scores)//2] if len(scores) >= 4 else []

    recent_avg = sum(recent_3) / len(recent_3)

    if older_3:
        older_avg = sum(older_3) / len(older_3)
        delta = recent_avg - older_avg
        if delta > 0.03:
            direction = "improving"
        elif delta < -0.03:
            direction = "declining"
        else:
            direction = "stable"
    else:
        delta = 0
        direction = "too_early"

    by_domain = {}
    for h in history:
        for r in h.get("results", []):
            d = r.get("domain", "unknown")
            by_domain.setdefault(d, []).append(r.get("invariant_score", 0))

    domain_trends = {}
    for d, domain_scores in by_domain.items():
        if len(domain_scores) >= 2:
            first_half = domain_scores[:len(domain_scores)//2]
            second_half = domain_scores[len(domain_scores)//2:]
            d_delta = (sum(second_half)/len(second_half)) - (sum(first_half)/len(first_half))
            domain_trends[d] = round(d_delta, 3)

    return {
        "status": direction,
        "total_records": len(history),
        "current_avg": round(recent_avg, 3),
        "delta": round(delta, 3),
        "domain_trends": domain_trends,
        "history_scores": [round(s, 3) for s in scores],
    }
