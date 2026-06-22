"""
治理机制反事实校准 — nudge/safety_net 的 precision/recall 分析

从历史 session logs 计算：
- 干预后结局变好 = 正确拦截 (TP)
- 干预后结局没变/变差 = 误报 (FP)
- 未干预但结局失败 = 漏报 (FN)
- 未干预且结局成功 = 正确放行 (TN)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import logging

log = logging.getLogger("educe.core.governance_calibration")

@dataclass
class InterventionStats:
    tp: int = 0  # 干预后成功（正确拦截/引导）
    fp: int = 0  # 干预后仍失败（误报/无效干预）
    fn: int = 0  # 未干预但失败（漏报）
    tn: int = 0  # 未干预且成功（正确放行）

    @property
    def precision(self) -> float:
        return self.tp / max(self.tp + self.fp, 1)

    @property
    def recall(self) -> float:
        return self.tp / max(self.tp + self.fn, 1)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / max(p + r, 0.001)

    def summary(self) -> str:
        total = self.tp + self.fp + self.fn + self.tn
        return (
            f"  TP={self.tp} (干预→成功) | FP={self.fp} (干预→仍失败)\n"
            f"  FN={self.fn} (未干预→失败) | TN={self.tn} (未干预→成功)\n"
            f"  Precision={self.precision:.2f} | Recall={self.recall:.2f} | F1={self.f1:.2f}\n"
            f"  Total sessions: {total}"
        )


def analyze_sessions(logs_dir: Path) -> dict[str, InterventionStats]:
    """分析所有 session 的治理机制有效性"""
    nudge_stats = InterventionStats()
    safety_stats = InterventionStats()

    for events_file in logs_dir.rglob("events.jsonl"):
        try:
            events = [json.loads(l) for l in events_file.read_text().strip().split("\n") if l.strip()]
        except Exception as e:
            log.debug("suppressed: %s", e)
            continue

        if len(events) < 3:
            continue

        # Determine session outcome
        session_end = next((e for e in reversed(events) if e.get("name") == "session_end"), None)
        turn_end = next((e for e in reversed(events) if e.get("name") == "turn_end"), None)

        outcome = "unknown"
        if session_end:
            outcome = session_end.get("data", {}).get("outcome", "unknown")
        elif turn_end:
            reason = turn_end.get("data", {}).get("reason", "")
            outcome = "completed" if reason == "no_action" else "partial"

        # Check for tool_result successes to better determine outcome
        tool_results = [e for e in events if e.get("type") == "tool_call"]
        has_successful_edit = any(
            e.get("data", {}).get("action_type") in ("edit_file", "write_file", "shell")
            and e.get("status") == "ok"
            for e in tool_results
        )
        # Success = has meaningful tool output, regardless of session_end status
        session_success = has_successful_edit

        # Count interventions
        nudge_count = sum(1 for e in events if e.get("name") == "nudge_triggered")
        safety_count = sum(1 for e in events if e.get("name") == "safety_net")

        had_nudge = nudge_count > 0
        had_safety = safety_count > 0

        # Nudge stats
        if had_nudge:
            if session_success:
                nudge_stats.tp += 1
            else:
                nudge_stats.fp += 1
        else:
            if session_success:
                nudge_stats.tn += 1
            else:
                nudge_stats.fn += 1

        # Safety net stats
        if had_safety:
            if session_success:
                safety_stats.tp += 1
            else:
                safety_stats.fp += 1
        else:
            if session_success:
                safety_stats.tn += 1
            else:
                safety_stats.fn += 1

    return {"nudge": nudge_stats, "safety_net": safety_stats}


def run_analysis(logs_dir: Path | None = None) -> None:
    """Run full analysis and print report"""
    logs_dir = logs_dir or Path(".educe/logs")

    # Also include benchmark logs
    all_dirs = [logs_dir]
    bench_dir = Path(".educe/benchmark_runs")
    if bench_dir.exists():
        all_dirs.extend(p for p in bench_dir.rglob("logs") if p.is_dir())

    combined_nudge = InterventionStats()
    combined_safety = InterventionStats()

    for d in all_dirs:
        stats = analyze_sessions(d)
        for attr in ("tp", "fp", "fn", "tn"):
            setattr(combined_nudge, attr, getattr(combined_nudge, attr) + getattr(stats["nudge"], attr))
            setattr(combined_safety, attr, getattr(combined_safety, attr) + getattr(stats["safety_net"], attr))

    print("=" * 50)
    print("  治理机制反事实校准报告")
    print("=" * 50)
    print()
    print("【Nudge（探索收敛引导）】")
    print(combined_nudge.summary())
    print()
    print("【Safety Net（安全网强制收敛）】")
    print(combined_safety.summary())
    print()

    # Fine-grained FN analysis
    true_fn = _count_true_fn(all_dirs)
    tp = combined_nudge.tp
    adjusted_recall = tp / max(tp + true_fn, 1)
    print(f"【修正后指标（排除不该管的 session）】")
    print(f"  真正漏报: {true_fn} (有探索≥3轮但未 nudge)")
    print(f"  修正 Recall: {adjusted_recall:.2f}")
    print()

    # Recommendations
    print("【建议】")
    if combined_nudge.precision < 0.5:
        print("  ⚠️ Nudge precision 低 — 干预频繁但效果差，考虑提高触发阈值")
    elif combined_nudge.precision > 0.7:
        print("  ✓ Nudge precision 良好")

    if adjusted_recall < 0.5:
        print("  ⚠️ 修正 recall 低 — 仍有大量真漏报")
    elif adjusted_recall > 0.7:
        print("  ✓ 修正 recall 良好 — 真正需要干预的大部分被覆盖")


def _count_true_fn(all_dirs: list[Path]) -> int:
    """统计真正的漏报：有探索≥3轮 + 无 nudge + 结局失败"""
    count = 0
    for logs_dir in all_dirs:
        for events_file in logs_dir.rglob("events.jsonl"):
            try:
                events = [json.loads(l) for l in events_file.read_text().strip().split("\n") if l.strip()]
            except Exception as e:
                log.debug("suppressed: %s", e)
                continue
            if len(events) < 3:
                continue

            tool_results = [e for e in events if e.get("type") == "tool_call"]
            has_edit = any(
                e.get("data", {}).get("action_type") in ("edit_file", "write_file", "shell")
                and e.get("status") == "ok"
                for e in tool_results
            )
            had_nudge = any(e.get("name") == "nudge_triggered" for e in events)
            has_exploration = any(
                e.get("data", {}).get("action_type") in ("read_file", "read_dir", "read_lines", "search_in_file")
                for e in tool_results
            )
            rounds = sum(1 for e in events if e.get("name") == "turn_start")

            if not had_nudge and not has_edit and has_exploration and rounds >= 3:
                count += 1
    return count


if __name__ == "__main__":
    run_analysis()
