"""Logging schema — dataclasses for Event, Trace, SessionSummary, SessionMeta."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


def _gen_id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> float:
    return time.time()


@dataclass
class Event:
    event_id: str = field(default_factory=_gen_id)
    ts: float = field(default_factory=_now)
    type: str = ""          # "framework"|"llm_call"|"tool_call"|"user"|"error"
    name: str = ""          # "session_start","llm_response","shell","nudge_triggered"
    status: str = "ok"      # "ok"|"error"|"partial"
    duration_ms: float | None = None
    summary: str = ""
    data: dict = field(default_factory=dict)
    trace_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["duration_ms"] is None:
            del d["duration_ms"]
        if d["trace_id"] is None:
            del d["trace_id"]
        if not d["data"]:
            del d["data"]
        return d


@dataclass
class Trace:
    trace_id: str = field(default_factory=_gen_id)
    ts: float = field(default_factory=_now)
    kind: str = ""          # "system_prompt"|"llm_output"|"tool_result"|"messages"
    payload: Any = None

    def to_dict(self) -> dict:
        return {"trace_id": self.trace_id, "ts": self.ts, "kind": self.kind, "payload": self.payload}


@dataclass
class SessionSummary:
    session_id: str = ""
    date: str = ""
    start_ts: float = 0.0
    end_ts: float | None = None
    status: str = "running"     # "running"|"completed"|"error"|"aborted"
    task: str = ""
    n_events: int = 0
    n_errors: int = 0
    model: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["end_ts"] is None:
            del d["end_ts"]
        return d


@dataclass
class SessionMeta:
    session_id: str = ""
    start_ts: float = field(default_factory=_now)
    educe_version: str = ""
    model: str = ""
    config: dict = field(default_factory=dict)
    git_sha: str = ""
    cwd: str = ""
    status: str = "running"

    def to_dict(self) -> dict:
        return asdict(self)
