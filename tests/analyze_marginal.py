"""
分析 marginal value 管道产出的数据

用法: PYTHONPATH=. python tests/analyze_marginal.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(".deepforge/experiments/marginal_data")


def analyze():
    if not DATA_DIR.exists():
        print("No data dir found. Run pipeline first.")
        return

    jsonl_files = sorted(DATA_DIR.glob("*_events.jsonl"))
    if not jsonl_files:
        print("No event files found.")
        return

    print(f"Found {len(jsonl_files)} scenario files\n")
    print(f"{'Scenario':<8} {'Cat':<10} {'Baseline':<10} {'Injected':<10} {'Withheld':<10} {'Delta':<8} {'MV':<6} {'BT'}")
    print("─" * 75)

    all_results = []
    for f in jsonl_files:
        events = [json.loads(l) for l in f.read_text().strip().split("\n") if l.strip()]
        if not events:
            continue

        sid = events[0]["scenario_id"]
        cat = events[0]["category"]

        baseline = [e for e in events if e["phase"] == "baseline"]
        injected = [e for e in events if e["phase"] == "mixed" and e.get("injected")]
        withheld = [e for e in events if e["phase"] == "mixed" and not e.get("injected")]

        b_rate = sum(e["compliant"] for e in baseline) / max(1, len(baseline))
        i_rate = sum(e["compliant"] for e in injected) / max(1, len(injected))
        w_rate = sum(e["compliant"] for e in withheld) / max(1, len(withheld))
        delta = i_rate - w_rate

        last = events[-1]
        mv = last.get("unit_marginal_value", "?")
        bt = last.get("unit_baseline_tests", "?")

        result = {
            "sid": sid, "category": cat,
            "baseline": b_rate, "injected": i_rate, "withheld": w_rate,
            "delta": delta, "mv": mv, "bt": bt,
            "n_injected": len(injected), "n_withheld": len(withheld),
        }
        all_results.append(result)

        delta_str = f"{delta:+.0%}"
        print(f"{sid:<8} {cat:<10} {b_rate:<10.0%} {i_rate:<10.0%} {w_rate:<10.0%} {delta_str:<8} {mv:<6} {bt}")

    # Summary by category
    print(f"\n{'='*75}")
    print("SUMMARY BY CATEGORY")
    print(f"{'='*75}\n")

    for cat in ["strong", "moderate", "weak"]:
        cat_results = [r for r in all_results if r["category"] == cat]
        if not cat_results:
            continue
        avg_delta = sum(r["delta"] for r in cat_results) / len(cat_results)
        avg_mv = sum(r["mv"] for r in cat_results if isinstance(r["mv"], (int, float))) / max(1, len(cat_results))
        avg_baseline = sum(r["baseline"] for r in cat_results) / len(cat_results)
        avg_injected = sum(r["injected"] for r in cat_results) / len(cat_results)

        print(f"{cat.upper()} (n={len(cat_results)}):")
        print(f"  Avg baseline compliance: {avg_baseline:.0%}")
        print(f"  Avg injected compliance: {avg_injected:.0%}")
        print(f"  Avg delta: {avg_delta:+.0%}")
        print(f"  Avg marginal_value: {avg_mv:.3f}")
        print()

    # System-level metrics
    total_injected = sum(r["n_injected"] for r in all_results)
    total_withheld = sum(r["n_withheld"] for r in all_results)
    useful_rules = sum(1 for r in all_results if r["delta"] > 0.1)
    redundant_rules = sum(1 for r in all_results if isinstance(r["mv"], (int, float)) and r["mv"] < 0.1 and r.get("bt", 0) >= 3)

    print(f"SYSTEM METRICS:")
    print(f"  Total injected turns: {total_injected}")
    print(f"  Total withheld turns: {total_withheld}")
    print(f"  Useful rules (delta > 10%): {useful_rules}/{len(all_results)}")
    print(f"  Redundant rules (mv < 0.1): {redundant_rules}/{len(all_results)}")
    print(f"  Prompt budget efficiency: {useful_rules / max(1, len(all_results)):.0%}")


if __name__ == "__main__":
    analyze()
