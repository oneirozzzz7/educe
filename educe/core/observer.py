"""
交互观测层
记录每次任务执行的全量数据，驱动框架自我进化
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
import logging

log = logging.getLogger("educe.core.observer")


class AgentTrace(BaseModel):
    agent: str
    started_at: float = 0
    finished_at: float = 0
    success: bool = True
    summary: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""

    @property
    def duration(self) -> float:
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return 0


class TaskTrace(BaseModel):
    task_id: str
    user_input: str
    model: str = ""
    started_at: float = Field(default_factory=time.time)
    finished_at: float = 0
    success: bool = False
    agent_traces: list[AgentTrace] = Field(default_factory=list)
    project_type: str = ""
    file_count: int = 0
    user_rating: int = 0  # 0=未评, 1-5
    user_feedback: str = ""
    iteration_count: int = 0
    error: str = ""

    @property
    def duration(self) -> float:
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return 0


class Observer:
    def __init__(self, storage_dir: str = ".educe/traces"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._current: TaskTrace | None = None

    def start_task(self, task_id: str, user_input: str, model: str = "") -> TaskTrace:
        self._current = TaskTrace(task_id=task_id, user_input=user_input, model=model)
        return self._current

    def start_agent(self, agent_name: str) -> None:
        if not self._current:
            return
        self._current.agent_traces.append(AgentTrace(agent=agent_name, started_at=time.time()))

    def finish_agent(self, agent_name: str, success: bool = True, summary: str = "", error: str = "") -> None:
        if not self._current:
            return
        for trace in reversed(self._current.agent_traces):
            if trace.agent == agent_name and trace.finished_at == 0:
                trace.finished_at = time.time()
                trace.success = success
                trace.summary = summary
                trace.error = error
                break

    def finish_task(self, success: bool = True, project_type: str = "", file_count: int = 0, error: str = "") -> TaskTrace | None:
        if not self._current:
            return None
        self._current.finished_at = time.time()
        self._current.success = success
        self._current.project_type = project_type
        self._current.file_count = file_count
        self._current.error = error
        self._save(self._current)
        trace = self._current
        self._current = None
        return trace

    def record_feedback(self, task_id: str, rating: int, feedback: str = "") -> None:
        path = self.storage_dir / f"{task_id}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text())
        data["user_rating"] = rating
        data["user_feedback"] = feedback
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _save(self, trace: TaskTrace) -> None:
        path = self.storage_dir / f"{trace.task_id}.json"
        path.write_text(json.dumps(trace.model_dump(), ensure_ascii=False, indent=2))

    def get_stats(self) -> dict[str, Any]:
        """汇总所有历史任务的统计数据"""
        traces = self._load_all()
        if not traces:
            return {"total_tasks": 0}

        total = len(traces)
        successes = sum(1 for t in traces if t.success)
        rated = [t for t in traces if t.user_rating > 0]
        avg_rating = sum(t.user_rating for t in rated) / len(rated) if rated else 0
        avg_duration = sum(t.duration for t in traces) / total if total else 0

        agent_stats: dict[str, dict] = {}
        for t in traces:
            for at in t.agent_traces:
                if at.agent not in agent_stats:
                    agent_stats[at.agent] = {"calls": 0, "successes": 0, "total_time": 0}
                agent_stats[at.agent]["calls"] += 1
                if at.success:
                    agent_stats[at.agent]["successes"] += 1
                agent_stats[at.agent]["total_time"] += at.duration

        for name, s in agent_stats.items():
            s["success_rate"] = s["successes"] / s["calls"] if s["calls"] else 0
            s["avg_time"] = s["total_time"] / s["calls"] if s["calls"] else 0

        model_usage: dict[str, int] = {}
        for t in traces:
            model_usage[t.model] = model_usage.get(t.model, 0) + 1

        return {
            "total_tasks": total,
            "success_rate": successes / total,
            "avg_duration": round(avg_duration, 1),
            "avg_rating": round(avg_rating, 1),
            "rated_count": len(rated),
            "agent_stats": agent_stats,
            "model_usage": model_usage,
            "recent_errors": [t.error for t in traces if t.error][-5:],
        }

    def _load_all(self) -> list[TaskTrace]:
        traces = []
        for path in sorted(self.storage_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                traces.append(TaskTrace.model_validate(data))
            except Exception as e:
                log.debug("suppressed: %s", e)
        return traces
