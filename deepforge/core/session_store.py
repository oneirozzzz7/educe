"""
DeepForge SessionStore
Session级存储——一个session一个文件，追加每轮QA pair。
替代task_store的per-turn碎片化存储。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


SESSION_DIR = Path(".educe/sessions")


class SessionStore:
    def __init__(self):
        SESSION_DIR.mkdir(parents=True, exist_ok=True)

    def append_turn(self, session_id: str, question: str, response: str,
                    turn_type: str = "text", domain: str = "",
                    metadata: dict = None):
        path = SESSION_DIR / "{}.jsonl".format(session_id[:16])
        turn = {
            "timestamp": time.time(),
            "question": question,
            "response": response[:10000],
            "type": turn_type,
            "domain": domain,
        }
        if metadata:
            turn["metadata"] = metadata
        with open(path, "a") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")

    def get_session(self, session_id: str) -> list:
        path = SESSION_DIR / "{}.jsonl".format(session_id[:16])
        if not path.exists():
            return []
        turns = []
        with open(path) as f:
            for line in f:
                try:
                    turns.append(json.loads(line))
                except Exception:
                    pass
        return turns

    def list_sessions(self, limit: int = 20, offset: int = 0) -> list:
        sessions = []
        paths = sorted(SESSION_DIR.glob("*.jsonl"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths[offset:offset + limit]:
            try:
                first_line = ""
                turn_count = 0
                last_type = "text"
                with open(path) as f:
                    for line in f:
                        turn_count += 1
                        if turn_count == 1:
                            first_line = line
                        last_line = line
                if first_line:
                    first = json.loads(first_line)
                    last = json.loads(last_line)
                    if last.get("type") == "code":
                        last_type = "code"
                    elif first.get("type") == "code":
                        last_type = "code"
                    sessions.append({
                        "id": path.stem,
                        "title": first.get("question", "")[:60],
                        "turns": turn_count,
                        "type": last_type,
                        "created_at": first.get("timestamp", 0),
                        "updated_at": last.get("timestamp", 0),
                    })
            except Exception:
                pass
        return sessions, len(paths)
