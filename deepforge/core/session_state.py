"""
SessionState — 统一的 session 级状态容器

基于统一事件流（events）设计。所有交互记录存为有序的 event 序列，
前端按序渲染即可完整还原历史。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


STATE_DIR = Path(".deepforge/state")


@dataclass
class SessionState:
    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # 任务核心
    user_request: str = ""
    phase: str = "idle"

    # 产物
    code_files: list[str] = field(default_factory=list)
    output_dir: str = ""
    current_version: int = 0
    versions: list[dict] = field(default_factory=list)

    # 统一事件流
    events: list[dict] = field(default_factory=list)

    # ─── 事件 API ───

    def add_event(self, event_type: str, **data) -> dict:
        event = {"type": event_type, "ts": time.time(), **data}
        self.events.append(event)
        self.updated_at = time.time()
        return event

    def add_user_input(self, content: str) -> dict:
        return self.add_event("user_input", content=content)

    def add_ai_reply(self, content: str) -> dict:
        return self.add_event("ai_reply", content=content[:10000])

    def add_think(self, content: str) -> dict:
        return self.add_event("think", content=content[:2000])

    def add_action_confirm(self, actions: list[dict]) -> dict:
        return self.add_event("action_confirm", actions=actions)

    def add_user_confirm(self, decision: str, note: str = "") -> dict:
        return self.add_event("user_confirm", decision=decision, note=note)

    def add_action_executed(self, action_type: str, result: str, success: bool = True) -> dict:
        return self.add_event("action_executed",
                             action=action_type, result=result[:1000], success=success)

    def add_build_start(self) -> dict:
        self.phase = "building"
        return self.add_event("build_start")

    def add_build_progress(self, step: str) -> dict:
        return self.add_event("build_progress", step=step)

    def add_build_complete(self, files: list[str], success: bool = True) -> dict:
        if success and files:
            self.code_files = files
            self.phase = "complete"
            self.current_version += 1
            self.versions.append({
                "version": self.current_version,
                "files": [Path(f).name for f in files],
                "timestamp": time.time(),
            })
        return self.add_event("build_complete",
                             files=[Path(f).name for f in files], success=success)

    def add_knowledge_change(self, op: str, content: str) -> dict:
        return self.add_event("knowledge_change", op=op, content=content[:200])

    # ─── 持久化 ───

    def reset(self) -> "SessionState":
        return SessionState(session_id=self.session_id)

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = STATE_DIR / "{}.json".format(self.session_id[:16])
        self.updated_at = time.time()
        data = asdict(self)
        path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")

    @classmethod
    def load(cls, session_id: str) -> "SessionState | None":
        path = STATE_DIR / "{}.json".format(session_id[:16])
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            return None

    @classmethod
    def load_or_create(cls, session_id: str) -> "SessionState":
        return cls.load(session_id) or cls(session_id=session_id)

    @classmethod
    def list_all(cls, limit: int = 20, offset: int = 0) -> list[dict]:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        sessions = []
        for f in sorted(STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                title = ""
                task_type = "text"
                for evt in data.get("events", []):
                    if evt.get("type") == "user_input" and not title:
                        title = evt.get("content", "")[:60]
                    if evt.get("type") == "build_complete":
                        task_type = "code"
                sessions.append({
                    "id": data.get("session_id", f.stem),
                    "title": title or "未命名",
                    "event_count": len(data.get("events", [])),
                    "type": task_type,
                    "created_at": data.get("created_at", 0),
                    "updated_at": data.get("updated_at", 0),
                    "current_version": data.get("current_version", 0),
                })
            except Exception:
                continue
        return sessions[offset:offset + limit]

    def to_snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "phase": self.phase,
            "user_request": self.user_request,
            "code_files": [Path(f).name for f in self.code_files],
            "output_dir": self.output_dir,
            "current_version": self.current_version,
            "versions": self.versions,
            "events": self.events,
        }
