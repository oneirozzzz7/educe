"""
Educe Benchmark Runner v2 — 自动化执行 + 日志采集 + 验收检查

架构：直接 import orchestrator（生产路径），每 case 独立 session + 隔离 workspace。
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from educe.core.config import EduceConfig
from educe.core.logging import SessionLogger
from educe.core.orchestrator import Orchestrator
from educe.models.router import ModelClient
import logging

log = logging.getLogger("educe.core.benchmark_runner")


@dataclass
class CaseResult:
    case_id: str
    level: str
    instruction: str
    model: str
    status: str = "pending"
    wall_time_s: float = 0.0
    events: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    acceptance: dict = field(default_factory=dict)
    session_id: str = ""
    workspace: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BenchmarkCase:
    case_id: str
    level: str  # L1/L2/L3
    domain: str
    instruction: str
    acceptance_checks: list[Callable[[CaseResult, Path], tuple[bool, float, str]]] = field(default_factory=list)
    fixture_dir: str | None = None
    needs_judge: bool = False
    timeout_s: float | None = None  # per-case override


def extract_metrics(events: list[dict]) -> dict:
    """从 events.jsonl 提取过程效率指标"""
    from collections import Counter

    total_rounds = sum(1 for e in events if e.get("name") == "llm_response")
    llm_time = sum(e.get("duration_ms", 0) for e in events if e.get("name") == "llm_response") / 1000
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    action_types = Counter(e.get("data", {}).get("action_type", "unknown") for e in tool_calls)
    nudge_count = sum(1 for e in events if e.get("name") == "nudge_triggered")
    safety_net = sum(1 for e in events if e.get("name") == "safety_net")
    errors = sum(1 for e in events if e.get("status") == "error")
    continuations = sum(1 for e in events if e.get("name") == "continuation")

    # Rounds to first meaningful action (non-read)
    meaningful_types = {"shell", "write_file", "edit_file", "build"}
    rounds_to_first = 0
    for e in events:
        if e.get("type") == "tool_call":
            at = e.get("data", {}).get("action_type", "")
            if at in meaningful_types:
                break
        if e.get("name") == "turn_start":
            rounds_to_first += 1

    # Redundant reads
    read_targets = []
    for e in events:
        if e.get("type") == "tool_call":
            at = e.get("data", {}).get("action_type", "")
            if at in ("read_file", "read_dir", "read_lines", "search_in_file"):
                read_targets.append(e.get("data", {}).get("action_name", "") or at)
    total_reads = len(read_targets)
    unique_reads = len(set(read_targets))
    redundant_ratio = (total_reads - unique_reads) / max(total_reads, 1)

    return {
        "total_rounds": total_rounds,
        "llm_time_s": round(llm_time, 2),
        "tool_call_count": len(tool_calls),
        "action_dist": dict(action_types),
        "nudge_count": nudge_count,
        "safety_net_count": safety_net,
        "error_count": errors,
        "continuation_count": continuations,
        "rounds_to_first_meaningful": rounds_to_first,
        "redundant_read_ratio": round(redundant_ratio, 3),
        "total_reads": total_reads,
        "total_tokens": sum(e.get("data", {}).get("total_tokens", 0) for e in events if e.get("name") == "llm_response"),
        "prompt_tokens": sum(e.get("data", {}).get("prompt_tokens", 0) for e in events if e.get("name") == "llm_response"),
        "completion_tokens": sum(e.get("data", {}).get("completion_tokens", 0) for e in events if e.get("name") == "llm_response"),
        "reflex_hits": sum(1 for e in events if e.get("name") == "reflex_hit"),
    }


class BenchmarkRunner:
    def __init__(
        self,
        cases: list[BenchmarkCase],
        model_name: str,
        api_key: str,
        base_url: str,
        run_id: str | None = None,
        output_dir: Path | None = None,
        timeout_s: float = 120.0,
        enable_skills: bool = True,
    ):
        self.cases = cases
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.run_id = run_id or time.strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or Path(f".educe/benchmark_runs/{self.run_id}/{model_name}")
        self.timeout_s = timeout_s
        self.enable_skills = enable_skills
        self.results: list[CaseResult] = []

    async def run_all(self) -> list[CaseResult]:
        """串行执行所有 case"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n{'='*60}")
        print(f"  Benchmark v2 | model={self.model_name} | cases={len(self.cases)}")
        print(f"  output: {self.output_dir}")
        print(f"{'='*60}\n")

        for i, case in enumerate(self.cases):
            print(f"[{i+1}/{len(self.cases)}] {case.case_id} (L{case.level}) ...", end=" ", flush=True)
            result = await self._run_case(case)
            self.results.append(result)
            status_icon = {"completed": "✓", "partial": "△", "timeout": "⏰", "error": "✗"}.get(result.status, "?")
            print(f"{status_icon} {result.wall_time_s:.1f}s | rounds={result.metrics.get('total_rounds', 0)} nudge={result.metrics.get('nudge_count', 0)}")

        self._save_summary()
        return self.results

    async def _run_case(self, case: BenchmarkCase) -> CaseResult:
        """执行单个 case"""
        session_id = uuid.uuid4().hex[:16]
        case_dir = self.output_dir / case.case_id
        workspace = case_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        # Copy fixture if needed
        if case.fixture_dir:
            fixture_src = Path(case.fixture_dir)
            if fixture_src.exists():
                shutil.copytree(fixture_src, workspace, dirs_exist_ok=True)

        result = CaseResult(
            case_id=case.case_id,
            level=case.level,
            instruction=case.instruction,
            model=self.model_name,
            session_id=session_id,
            workspace=str(workspace),
            status="running",
        )

        # Create config with model settings
        cfg = EduceConfig.load()
        cfg.default_model.model = self.model_name
        cfg.default_model.api_key = self.api_key
        cfg.default_model.base_url = self.base_url

        # Create orchestrator with session logger
        orchestrator = Orchestrator(cfg)
        log_dir = case_dir / "logs"
        sl = SessionLogger(session_id=session_id, model=self.model_name, base_dir=log_dir)
        orchestrator.session_logger = sl
        orchestrator.context.metadata["session_id"] = session_id
        orchestrator.context.metadata["_project_context_path"] = str(workspace)
        # Benchmark mode: auto-confirm all actions (no human in the loop)
        orchestrator.context.metadata["_benchmark_auto_confirm"] = True

        # CompositeSkill A/B: disable skill injection for baseline runs
        if not self.enable_skills:
            orchestrator._match_composite_skills = lambda *a, **kw: ""

        # Register agents
        client = ModelClient(api_key=self.api_key, base_url=self.base_url)
        from educe.agents import ALL_AGENTS
        for agent_cls in ALL_AGENTS:
            try:
                agent = agent_cls(config=cfg, model_client=client, knowledge=orchestrator.knowledge)
                orchestrator.register(agent)
            except Exception as e:
                log.debug("suppressed: %s", e)

        # Execute with timeout
        case_timeout = case.timeout_s or self.timeout_s
        t0 = time.time()
        try:
            await asyncio.wait_for(
                orchestrator.run(case.instruction),
                timeout=case_timeout,
            )
            result.status = "completed"
        except asyncio.TimeoutError:
            result.status = "timeout"
        except Exception as e:
            result.status = "error"
            result.error = str(e)[:500]

        result.wall_time_s = round(time.time() - t0, 2)
        sl.close(result.status)

        # Read events and extract metrics
        events_file = log_dir / "sessions" / time.strftime("%Y-%m-%d") / session_id[:16] / "events.jsonl"
        if events_file.exists():
            events = [json.loads(line) for line in events_file.read_text().strip().split("\n") if line.strip()]
            result.events = events
            result.metrics = extract_metrics(events)

        # Run acceptance checks
        if case.acceptance_checks and result.status in ("completed", "partial"):
            checks_passed = 0
            checks_total = len(case.acceptance_checks)
            details = []
            for check_fn in case.acceptance_checks:
                try:
                    passed, score, detail = check_fn(result, workspace)
                    checks_passed += score
                    details.append({"passed": passed, "score": score, "detail": detail})
                except Exception as e:
                    details.append({"passed": False, "score": 0, "detail": f"check error: {e}"})
            result.acceptance = {
                "score": round(checks_passed / max(checks_total, 1), 3),
                "checks": details,
            }

        # Save case result
        result_file = case_dir / "result.json"
        result_file.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

        return result

    def _save_summary(self):
        """Save run-level summary"""
        summary = {
            "run_id": self.run_id,
            "model": self.model_name,
            "total_cases": len(self.results),
            "completed": sum(1 for r in self.results if r.status == "completed"),
            "partial": sum(1 for r in self.results if r.status == "partial"),
            "timeout": sum(1 for r in self.results if r.status == "timeout"),
            "error": sum(1 for r in self.results if r.status == "error"),
            "avg_wall_time_s": round(sum(r.wall_time_s for r in self.results) / max(len(self.results), 1), 2),
            "avg_rounds": round(sum(r.metrics.get("total_rounds", 0) for r in self.results) / max(len(self.results), 1), 1),
            "total_nudges": sum(r.metrics.get("nudge_count", 0) for r in self.results),
            "cases": [r.to_dict() for r in self.results],
        }
        summary_file = self.output_dir / "summary.json"
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"\n{'='*60}")
        print(f"  Summary: {summary['completed']}/{summary['total_cases']} completed")
        print(f"  Avg time: {summary['avg_wall_time_s']}s | Avg rounds: {summary['avg_rounds']}")
        print(f"  Nudges: {summary['total_nudges']} | Timeouts: {summary['timeout']} | Errors: {summary['error']}")
        print(f"  Saved: {summary_file}")
        print(f"{'='*60}\n")


async def run_ab_comparison(
    cases: list[BenchmarkCase],
    model_name: str,
    api_key: str,
    base_url: str,
    timeout_s: float = 120.0,
) -> dict:
    """
    A/B 对照：分别运行 skill_off (baseline) 和 skill_on (treatment)，
    返回对比结果。
    """
    run_id = time.strftime("%Y%m%d_%H%M%S")

    # Baseline: skills OFF
    runner_off = BenchmarkRunner(
        cases=cases, model_name=model_name,
        api_key=api_key, base_url=base_url,
        run_id=f"{run_id}_skill_off",
        timeout_s=timeout_s, enable_skills=False,
    )
    print("\n" + "=" * 60)
    print("  A/B Phase 1: SKILL OFF (baseline)")
    print("=" * 60)
    results_off = await runner_off.run_all()

    # Treatment: skills ON
    runner_on = BenchmarkRunner(
        cases=cases, model_name=model_name,
        api_key=api_key, base_url=base_url,
        run_id=f"{run_id}_skill_on",
        timeout_s=timeout_s, enable_skills=True,
    )
    print("\n" + "=" * 60)
    print("  A/B Phase 2: SKILL ON (treatment)")
    print("=" * 60)
    results_on = await runner_on.run_all()

    # Compare
    off_rounds = [r.metrics.get("total_rounds", 0) for r in results_off if r.status == "completed"]
    on_rounds = [r.metrics.get("total_rounds", 0) for r in results_on if r.status == "completed"]
    off_tools = [r.metrics.get("tool_call_count", 0) for r in results_off if r.status == "completed"]
    on_tools = [r.metrics.get("tool_call_count", 0) for r in results_on if r.status == "completed"]

    avg_off_r = sum(off_rounds) / max(len(off_rounds), 1)
    avg_on_r = sum(on_rounds) / max(len(on_rounds), 1)
    avg_off_t = sum(off_tools) / max(len(off_tools), 1)
    avg_on_t = sum(on_tools) / max(len(on_tools), 1)

    delta_rounds = (avg_on_r - avg_off_r) / max(avg_off_r, 0.1) * 100
    delta_tools = (avg_on_t - avg_off_t) / max(avg_off_t, 0.1) * 100

    comparison = {
        "run_id": run_id,
        "model": model_name,
        "cases_count": len(cases),
        "baseline_completed": len(off_rounds),
        "treatment_completed": len(on_rounds),
        "avg_rounds_off": round(avg_off_r, 1),
        "avg_rounds_on": round(avg_on_r, 1),
        "rounds_delta_pct": round(delta_rounds, 1),
        "avg_tools_off": round(avg_off_t, 1),
        "avg_tools_on": round(avg_on_t, 1),
        "tools_delta_pct": round(delta_tools, 1),
        "target_met": delta_rounds <= -40,
    }

    print("\n" + "=" * 60)
    print("  A/B COMPARISON RESULTS")
    print("=" * 60)
    print(f"  {'Metric':<20} {'Skill OFF':<12} {'Skill ON':<12} {'Delta':<10}")
    print(f"  {'-' * 54}")
    print(f"  {'Avg Rounds':<20} {avg_off_r:<12.1f} {avg_on_r:<12.1f} {delta_rounds:+.1f}%")
    print(f"  {'Avg Tool Calls':<20} {avg_off_t:<12.1f} {avg_on_t:<12.1f} {delta_tools:+.1f}%")
    print(f"\n  Target: rounds reduction >= 40%")
    passed = "✅ PASS" if delta_rounds <= -40 else ("⚠️ partial" if delta_rounds < 0 else "❌ regression")
    print(f"  Result: {passed} ({delta_rounds:+.1f}%)")
    print("=" * 60)

    # Save comparison
    comp_file = Path(f".educe/benchmark_runs/{run_id}_comparison.json")
    comp_file.parent.mkdir(parents=True, exist_ok=True)
    comp_file.write_text(json.dumps(comparison, ensure_ascii=False, indent=2))

    return comparison
