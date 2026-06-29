"""LongitudinalRunner — 纵向实验引擎

同一任务重复 N 次，共享 .educe/ 状态（记忆+技能+ledger），
但每次 run 给全新 workspace。用于验证 The Descent Curve：
行为成本随经验单调下降。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("educe.longitudinal")


@dataclass
class TaskFamily:
    family_id: str
    instruction: str
    acceptance_check: Callable[[Any, Path], tuple[bool, float, str]]
    fixture_dir: str | None = None


@dataclass
class RunResult:
    run_idx: int
    llm_calls: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wall_clock_s: float = 0.0
    reflex_hits: int = 0
    correct: bool = False
    score: float = 0.0
    status: str = "pending"
    error: str = ""
    metrics: dict = field(default_factory=dict)


class LongitudinalRunner:
    """Runs the same task N times with shared .educe/ state."""

    def __init__(
        self,
        task_family: TaskFamily,
        n_runs: int = 15,
        model_name: str = "Qwen3-235B-A22B",
        api_key: str = "",
        base_url: str = "",
        output_dir: Path | None = None,
        timeout_s: float = 120.0,
    ):
        self.family = task_family
        self.n_runs = n_runs
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_s = timeout_s

        self.output_dir = output_dir or Path(f".educe/descent/{task_family.family_id}")
        self.shared_educe = self.output_dir / "shared_educe"
        self.results: list[RunResult] = []

    async def run_all(self) -> list[RunResult]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.shared_educe.mkdir(parents=True, exist_ok=True)
        self._episode_dir = self.shared_educe / "episodes"
        self._episode_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"  Descent Curve | family={self.family.family_id}")
        print(f"  model={self.model_name} | runs={self.n_runs}")
        print(f"  shared_educe: {self.shared_educe}")
        print(f"{'='*60}\n")

        for run_idx in range(self.n_runs):
            print(f"  [{run_idx+1}/{self.n_runs}] ", end="", flush=True)
            result = await self._run_single(run_idx)
            self.results.append(result)
            icon = "✓" if result.correct else "✗"
            print(f"{icon} tokens={result.total_tokens} calls={result.llm_calls} "
                  f"reflex={result.reflex_hits} wall={result.wall_clock_s:.1f}s")

        self._save_results()
        return self.results

    async def _run_single(self, run_idx: int) -> RunResult:
        from educe.core.benchmark_runner import extract_metrics
        from educe.core.logging.session_logger import SessionLogger
        from educe.core.orchestrator import Orchestrator
        from educe.core.config import EduceConfig
        from educe.models.router import ModelClient

        session_id = uuid.uuid4().hex[:16]
        run_dir = (self.output_dir / f"run_{run_idx:02d}").resolve()
        workspace = run_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        # Copy fixture files if any
        if self.family.fixture_dir:
            src = Path(self.family.fixture_dir)
            if src.exists():
                shutil.copytree(src, workspace, dirs_exist_ok=True)

        # Symlink .educe in workspace -> shared state
        educe_link = workspace / ".educe"
        if educe_link.exists() or educe_link.is_symlink():
            educe_link.unlink()
        educe_link.symlink_to(self.shared_educe.resolve())

        result = RunResult(run_idx=run_idx)

        # Configure
        cfg = EduceConfig.load()
        cfg.default_model.model = self.model_name
        cfg.default_model.api_key = self.api_key
        cfg.default_model.base_url = self.base_url

        # Create orchestrator
        orchestrator = Orchestrator(cfg)
        log_dir = run_dir / "logs"
        sl = SessionLogger(session_id=session_id, model=self.model_name, base_dir=log_dir)
        orchestrator.session_logger = sl
        orchestrator.context.metadata["session_id"] = session_id
        orchestrator.context.metadata["_project_context_path"] = str(workspace)
        orchestrator.context.metadata["_benchmark_auto_confirm"] = True

        # Register agents (required for _get_client() to work)
        client = ModelClient(api_key=self.api_key, base_url=self.base_url)
        try:
            from educe.agents import ALL_AGENTS
            for agent_cls in ALL_AGENTS:
                try:
                    agent = agent_cls(config=cfg, model_client=client, knowledge=orchestrator.knowledge)
                    orchestrator.register(agent)
                except Exception:
                    pass
        except ImportError:
            from educe.core.agent import BaseAgent
            class _MinimalAgent(BaseAgent):
                name = "default"
                def __init__(self, mc):
                    self.model_client = mc
            orchestrator.agents = {"default": _MinimalAgent(client)}

        # Episode injection: load best prior episode as context hint
        episode_hint = self._load_best_episode()
        if episode_hint:
            orchestrator.context.metadata["_episode_hint"] = episode_hint

        # Execute (cd to workspace so ProjectMemoryStore resolves .educe/ via symlink)
        original_cwd = os.getcwd()
        os.chdir(workspace)
        t0 = time.time()
        try:
            await asyncio.wait_for(
                orchestrator.run(self.family.instruction),
                timeout=self.timeout_s,
            )
            result.status = "completed"
        except asyncio.TimeoutError:
            result.status = "timeout"
        except Exception as e:
            result.status = "error"
            result.error = str(e)[:300]
        finally:
            os.chdir(original_cwd)

        result.wall_clock_s = round(time.time() - t0, 2)
        sl.close(result.status)

        # Save conversation for acceptance checks
        reply_file = run_dir / "reply.txt"
        try:
            turns = getattr(orchestrator, 'conversation', None)
            if turns and hasattr(turns, 'turns'):
                reply_parts = [t.content for t in turns.turns if t.role == "assistant"]
                reply_file.write_text("\n".join(reply_parts), encoding="utf-8")
        except Exception:
            pass

        # Extract metrics from events
        events_file = self._find_events_file(log_dir, session_id)
        if events_file and events_file.exists():
            events = [json.loads(line) for line in events_file.read_text().strip().split("\n") if line.strip()]
            metrics = extract_metrics(events)
            result.metrics = metrics
            result.llm_calls = metrics.get("total_rounds", 0)
            result.total_tokens = metrics.get("total_tokens", 0)
            result.prompt_tokens = metrics.get("prompt_tokens", 0)
            result.completion_tokens = metrics.get("completion_tokens", 0)
            result.reflex_hits = metrics.get("reflex_hits", 0)

        # Acceptance check
        try:
            passed, score, detail = self.family.acceptance_check(result, workspace)
            result.correct = passed
            result.score = score
        except Exception as e:
            log.warning("acceptance check failed: %s", e)
            result.correct = False
            result.score = 0.0

        # Save episode if run was successful (for next run's context injection)
        if result.correct and result.status == "completed":
            self._save_episode(run_idx, orchestrator)

        # Save individual run result
        result_file = run_dir / "result.json"
        result_file.write_text(json.dumps({
            "run_idx": result.run_idx,
            "status": result.status,
            "llm_calls": result.llm_calls,
            "total_tokens": result.total_tokens,
            "wall_clock_s": result.wall_clock_s,
            "reflex_hits": result.reflex_hits,
            "correct": result.correct,
            "score": result.score,
            "metrics": result.metrics,
        }, ensure_ascii=False, indent=2))

        return result

    def _find_events_file(self, log_dir: Path, session_id: str) -> Path | None:
        import glob
        pattern = str(log_dir / "sessions" / "*" / session_id[:16] / "events.jsonl")
        matches = glob.glob(pattern)
        return Path(matches[0]) if matches else None

    def _save_results(self):
        summary = {
            "family_id": self.family.family_id,
            "model": self.model_name,
            "n_runs": self.n_runs,
            "runs": [
                {
                    "run_idx": r.run_idx,
                    "llm_calls": r.llm_calls,
                    "total_tokens": r.total_tokens,
                    "wall_clock_s": r.wall_clock_s,
                    "reflex_hits": r.reflex_hits,
                    "correct": r.correct,
                    "score": r.score,
                }
                for r in self.results
            ],
        }
        out = self.output_dir / "summary.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"\n  Summary saved: {out}")

    def _save_episode(self, run_idx: int, orchestrator):
        """Save successful action trace as a verified episode for future runs."""
        try:
            # Get actions from events.jsonl (more reliable than conversation turns)
            run_dir = (self.output_dir / f"run_{run_idx:02d}").resolve()
            events_file = self._find_events_file(run_dir / "logs",
                orchestrator.context.metadata.get("session_id", "x"))
            if not events_file or not events_file.exists():
                return

            actions = []
            for line in events_file.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                e = json.loads(line)
                if e.get("type") == "tool_call":
                    actions.append({
                        "type": e.get("data", {}).get("action_type", e.get("name", "")),
                        "params": e.get("data", {}).get("cmd", "") or e.get("summary", "")[:200],
                    })

            if not actions:
                return

            episode = {
                "run_idx": run_idx,
                "instruction": self.family.instruction,
                "actions": actions,
                "action_count": len(actions),
            }
            ep_file = self._episode_dir / f"episode_{run_idx:02d}.json"
            ep_file.write_text(json.dumps(episode, ensure_ascii=False, indent=2))
        except Exception as e:
            log.debug("episode save failed: %s", e)

    def _load_best_episode(self) -> str:
        """Load the most recent successful episode as a hint for the model."""
        try:
            episodes = sorted(self._episode_dir.glob("episode_*.json"), reverse=True)
            if not episodes:
                return ""

            ep = json.loads(episodes[0].read_text())
            actions = ep.get("actions", [])
            if not actions:
                return ""

            steps = []
            for i, a in enumerate(actions, 1):
                params_short = a["params"][:80] if a.get("params") else ""
                steps.append(f"  {i}. {a['type']}: {params_short}")

            hint = (
                f"## Prior successful execution\n"
                f"This exact task was completed successfully before using these steps:\n"
                + "\n".join(steps) + "\n"
                f"You may reuse this approach directly without re-exploration."
            )
            return hint
        except Exception as e:
            log.debug("episode load failed: %s", e)
            return ""
