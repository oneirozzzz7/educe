"""SessionLogger — core implementation for structured event logging."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .schema import Event, Trace, SessionSummary, SessionMeta, _gen_id, _now
from .writer import JsonlWriter

_TRACE_ENABLED = os.environ.get("EDUCE_TRACE", "1") != "0"

_active_logger: "SessionLogger | None" = None


def get_logger() -> "SessionLogger | None":
    return _active_logger


class SessionLogger:
    def __init__(
        self,
        session_id: str,
        model: str = "",
        config: dict | None = None,
        base_dir: Path | None = None,
    ):
        self.session_id = session_id
        self.model = model
        self._start_ts = _now()
        self._n_events = 0
        self._n_errors = 0
        self._task = ""

        base = base_dir or Path(".educe/logs")
        date_str = time.strftime("%Y-%m-%d")
        session_dir = base / "sessions" / date_str / session_id[:16]
        session_dir.mkdir(parents=True, exist_ok=True)

        self._session_dir = session_dir
        self._events_writer = JsonlWriter(session_dir / "events.jsonl")
        self._trace_writer = JsonlWriter(session_dir / "trace.jsonl") if _TRACE_ENABLED else None
        self._index_writer = JsonlWriter(base / "index.jsonl")

        self._meta = SessionMeta(
            session_id=session_id,
            start_ts=self._start_ts,
            educe_version=self._get_version(),
            model=model,
            config=config or {},
            git_sha=self._get_git_sha(),
            cwd=os.getcwd(),
            status="running",
        )
        self._write_meta()

        global _active_logger
        _active_logger = self

    def event(
        self,
        type: str,
        name: str,
        *,
        status: str = "ok",
        duration_ms: float | None = None,
        summary: str = "",
        data: dict | None = None,
        trace_payload: Any = None,
        trace_kind: str = "",
    ) -> Event:
        trace_id = None
        if trace_payload is not None and self._trace_writer and _TRACE_ENABLED:
            trace_id = _gen_id()
            trace = Trace(trace_id=trace_id, ts=_now(), kind=trace_kind or name, payload=trace_payload)
            self._trace_writer.append(trace.to_dict())

        evt = Event(
            ts=_now(),
            type=type,
            name=name,
            status=status,
            duration_ms=duration_ms,
            summary=summary,
            data=data or {},
            trace_id=trace_id,
        )
        self._events_writer.append(evt.to_dict())
        self._n_events += 1
        if status == "error":
            self._n_errors += 1
        return evt

    def set_task(self, task: str) -> None:
        self._task = task[:200]

    def close(self, status: str = "completed") -> None:
        duration_ms = (_now() - self._start_ts) * 1000
        self.event(
            type="framework",
            name="session_end",
            status="ok" if status == "completed" else status,
            duration_ms=duration_ms,
            summary=f"session ended: {status}",
            data={"outcome": status, "n_events": self._n_events,
                  "n_errors": self._n_errors, "duration_s": round(duration_ms / 1000, 1)},
        )

        self._meta.status = status
        self._write_meta()

        summary = SessionSummary(
            session_id=self.session_id,
            date=time.strftime("%Y-%m-%d"),
            start_ts=self._start_ts,
            end_ts=_now(),
            status=status,
            task=self._task,
            n_events=self._n_events,
            n_errors=self._n_errors,
            model=self.model,
        )
        self._index_writer.append(summary.to_dict())

        self._events_writer.close()
        if self._trace_writer:
            self._trace_writer.close()
        self._index_writer.close()

        global _active_logger
        if _active_logger is self:
            _active_logger = None

    def _write_meta(self) -> None:
        meta_path = self._session_dir / "meta.json"
        meta_path.write_text(
            json.dumps(self._meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _get_version() -> str:
        try:
            from educe import __version__
            return __version__
        except Exception:
            return "unknown"

    @staticmethod
    def _get_git_sha() -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=2,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""
