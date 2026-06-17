"""
用户活动日志（Activity Log）

记录用户与系统的每一次关键交互，结构化 JSON 行，按日期分文件。
用于监控、调试、进化分析。

每条日志包含：timestamp, session_id, event, detail
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


_LOG_DIR = Path(".educe/logs")


def _ensure_dir():
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_activity(session_id: str, event: str, **detail):
    """写一条结构化活动日志"""
    _ensure_dir()
    now = time.localtime()
    day_file = _LOG_DIR / f"activity_{now.tm_year}{now.tm_mon:02d}{now.tm_mday:02d}.jsonl"
    record = {
        "ts": time.time(),
        "time": time.strftime("%H:%M:%S", now),
        "sid": session_id[:12] if session_id else "-",
        "event": event,
        **detail,
    }
    with open(day_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
