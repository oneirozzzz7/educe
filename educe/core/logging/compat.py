"""Compat shim — bridges old log_activity() calls to the new SessionLogger.

During transition period, all existing `from educe.core.activity_log import log_activity`
calls continue working. When a SessionLogger is active, events are written to the
new structured log. Otherwise, noop.
"""
from __future__ import annotations

from .session_logger import get_logger


def log_activity(session_id: str, event: str, **detail):
    """Write a structured event via the active SessionLogger, or noop."""
    logger = get_logger()
    if logger is None:
        return

    event_type = _infer_type(event)
    summary_parts = [f"{k}={v}" for k, v in list(detail.items())[:4] if v]
    summary = f"{event}: {', '.join(summary_parts)}" if summary_parts else event

    logger.event(
        type=event_type,
        name=event,
        summary=summary[:200],
        data=detail,
    )


def _infer_type(event_name: str) -> str:
    if event_name.startswith("shell") or event_name.startswith("action"):
        return "tool_call"
    if event_name.startswith("model") or event_name.startswith("llm"):
        return "llm_call"
    if event_name.startswith("user") or event_name.startswith("knowledge"):
        return "user"
    if event_name.startswith("error"):
        return "error"
    return "framework"
