"""
SessionState — 统一的 session 级状态容器

单一数据源：所有 session 状态集中在此对象，持久化到磁盘。
消除了之前 artifacts/metadata/conversation/disk 四层各自为政的问题。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


STATE_DIR = Path(".deepforge/state")


@dataclass
class SessionState:
    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # 任务核心
    user_request: str = ""
    phase: str = "idle"  # idle | building | complete
    complexity: str = ""  # simple | complex | ""

    # 产物
    code_files: list[str] = field(default_factory=list)
    output_dir: str = ""
    current_version: int = 0
    versions: list[dict] = field(default_factory=list)  # [{version, files, timestamp}]

    # 过程记录
    transcript: list[dict] = field(default_factory=list)  # [{phase, role, content, elapsed}]
    turns: list[dict] = field(default_factory=list)  # [{role, content, timestamp, type}]

    # 模型上下文
    plan_summary: str = ""
    step_plan: list[str] = field(default_factory=list)
    expert_name: str = ""

    # ─── Methods ───

    def add_turn(self, role: str, content: str, turn_type: str = "text") -> None:
        self.turns.append({
            "role": role,
            "content": content[:10000],
            "timestamp": time.time(),
            "type": turn_type,
        })
        self.updated_at = time.time()

    def add_transcript(self, phase: str, role: str, content: str, elapsed: float = 0.0) -> dict:
        entry = {"phase": phase, "role": role, "content": content, "elapsed": elapsed}
        self.transcript.append(entry)
        self.updated_at = time.time()
        return entry

    def set_build_complete(self, code_files: list[str], output_dir: str, version: int) -> None:
        self.code_files = code_files
        self.output_dir = output_dir
        self.current_version = version
        self.phase = "complete"
        self.versions.append({
            "version": version,
            "files": [Path(f).name for f in code_files],
            "timestamp": time.time(),
        })
        self.updated_at = time.time()

    def reset(self) -> "SessionState":
        """Create a fresh state (new task on same session)."""
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
        state = cls.load(session_id)
        if state:
            return state
        return cls(session_id=session_id)

    @classmethod
    def list_all(cls, limit: int = 20, offset: int = 0) -> list[dict]:
        """List all sessions for sidebar, sorted by updated_at desc."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        sessions = []
        for f in sorted(STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                first_user = ""
                for t in data.get("turns", []):
                    if t.get("role") == "user":
                        first_user = t.get("content", "")[:60]
                        break
                sessions.append({
                    "id": data.get("session_id", f.stem),
                    "title": first_user or data.get("user_request", "")[:60] or "未命名",
                    "turns": len(data.get("turns", [])),
                    "type": "code" if data.get("code_files") else "text",
                    "created_at": data.get("created_at", 0),
                    "updated_at": data.get("updated_at", 0),
                    "current_version": data.get("current_version", 0),
                })
            except Exception:
                continue
        return sessions[offset:offset + limit]

    def to_snapshot(self) -> dict:
        """Return a JSON-serializable snapshot for frontend state_sync."""
        return {
            "session_id": self.session_id,
            "phase": self.phase,
            "user_request": self.user_request,
            "code_files": [Path(f).name for f in self.code_files],
            "output_dir": self.output_dir,
            "current_version": self.current_version,
            "versions": self.versions,
            "transcript": self.transcript,
            "turns": self.turns,
            "plan_summary": self.plan_summary,
            "step_plan": self.step_plan,
            "complexity": self.complexity,
            "expert_name": self.expert_name,
        }
