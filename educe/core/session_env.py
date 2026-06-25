"""Session State — 环境事实的唯一权威源

与对话历史分离，永不压缩。每轮作为 <env> 块注入模型上下文。

修复 Opus 4.8 审查指出的问题：
- project_root 带 source（防低可信覆盖高可信）
- 无 I/O 副作用（不调 is_dir）
- inject_env 每轮去重（防累积）
- pinned_paths 带 turn_id（按时间排序）
- Fact.to_dict 保留 ts
- schema version
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FactSource(Enum):
    USER_EXPLICIT = "user_explicit"
    AT_REFERENCE = "at_reference"
    TOOL_VERIFIED = "tool_verified"
    INFERRED = "inferred"


_PRIORITY = {
    FactSource.INFERRED: 0,
    FactSource.AT_REFERENCE: 1,
    FactSource.TOOL_VERIFIED: 2,
    FactSource.USER_EXPLICIT: 3,
}


@dataclass
class Fact:
    key: str
    value: str
    source: FactSource
    turn_id: int
    ts: float = field(default_factory=time.time)
    verified: bool = False

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "source": self.source.value,
                "turn_id": self.turn_id, "ts": self.ts, "verified": self.verified}

    @classmethod
    def from_dict(cls, d: dict) -> "Fact":
        return cls(key=d["key"], value=d["value"],
                   source=FactSource(d.get("source", "inferred")),
                   turn_id=d.get("turn_id", 0), ts=d.get("ts", 0),
                   verified=d.get("verified", False))


@dataclass
class SessionState:
    """环境事实层，与对话历史独立，永不压缩。"""

    project_root: Optional[str] = None
    project_root_source: Optional[FactSource] = None
    cwd: Optional[str] = None
    pinned_paths: list[dict] = field(default_factory=list)
    confirmed_facts: dict[str, Fact] = field(default_factory=dict)
    _version: int = 1

    def set_project_root(self, path: str, source: FactSource, turn_id: int = 0):
        """设置项目根。只有更高可信来源可覆盖。"""
        if self.project_root and self.project_root != path:
            existing_p = _PRIORITY.get(self.project_root_source, 0) if self.project_root_source else 0
            new_p = _PRIORITY.get(source, 0)
            if new_p < existing_p:
                return
            self.pinned_paths = []
            self.confirmed_facts = {
                k: f for k, f in self.confirmed_facts.items()
                if f.source == FactSource.USER_EXPLICIT
            }
        self.project_root = path
        self.project_root_source = source
        if not self.cwd:
            self.cwd = path

    def update_cwd(self, path: str, turn_id: int = 0):
        self.cwd = path

    def pin_path(self, path: str, source: FactSource = FactSource.AT_REFERENCE, turn_id: int = 0):
        self.pinned_paths = [p for p in self.pinned_paths if p["path"] != path]
        self.pinned_paths.append({"path": path, "source": source.value, "turn_id": turn_id})

    def add_fact(self, key: str, value: str, source: FactSource, turn_id: int = 0):
        existing = self.confirmed_facts.get(key)
        if existing:
            if _PRIORITY.get(existing.source, 0) > _PRIORITY.get(source, 0):
                return
        self.confirmed_facts[key] = Fact(
            key=key, value=value, source=source, turn_id=turn_id,
            verified=(source == FactSource.TOOL_VERIFIED))

    def is_empty(self) -> bool:
        return not (self.project_root or self.cwd or
                    self.confirmed_facts or self.pinned_paths)

    def render(self) -> str:
        if self.is_empty():
            return ""
        lines = []
        if self.project_root:
            lines.append(f"root: {self.project_root}")
        if self.cwd and self.cwd != self.project_root:
            lines.append(f"cwd: {self.cwd}")
        if self.pinned_paths:
            recent = sorted(self.pinned_paths, key=lambda x: -x.get("turn_id", 0))[:5]
            lines.append("pinned: " + ", ".join(p["path"] for p in recent))
        if self.confirmed_facts:
            lines.append("facts:")
            for f in sorted(self.confirmed_facts.values(), key=lambda x: -x.turn_id)[:8]:
                tag = " (verified)" if f.verified else ""
                lines.append(f"  {f.key}={f.value}{tag}")
        return "<env>\n" + "\n".join(lines) + "\n</env>"

    def to_disk(self) -> dict:
        return {
            "_version": self._version,
            "project_root": self.project_root,
            "project_root_source": self.project_root_source.value if self.project_root_source else None,
            "cwd": self.cwd,
            "pinned_paths": self.pinned_paths[-10:],
            "confirmed_facts": {
                k: f.to_dict() for k, f in self.confirmed_facts.items()
                if f.source in (FactSource.TOOL_VERIFIED, FactSource.USER_EXPLICIT)
            },
        }

    @classmethod
    def from_disk(cls, data: dict) -> "SessionState":
        state = cls()
        state.project_root = data.get("project_root")
        src = data.get("project_root_source")
        state.project_root_source = FactSource(src) if src else None
        state.cwd = data.get("cwd")
        state.pinned_paths = data.get("pinned_paths", [])
        for k, fd in data.get("confirmed_facts", {}).items():
            state.confirmed_facts[k] = Fact.from_dict(fd)
        return state


# ═══ @path 检测（纯字符串，无 I/O）═══

_AT_PATH_RE = re.compile(r"@(/[^\s,，。！？)）;；]+)")


def extract_at_paths(user_input: str) -> list[str]:
    paths = _AT_PATH_RE.findall(user_input)
    return [p.rstrip("/.") or p for p in paths if p]


def update_state_from_input(state: SessionState, user_input: str, turn_id: int = 0):
    """从用户输入检测 @ 引用，更新 state。无 I/O。"""
    paths = extract_at_paths(user_input)
    for path in paths:
        state.pin_path(path, FactSource.AT_REFERENCE, turn_id)
        state.set_project_root(path, FactSource.AT_REFERENCE, turn_id)


# ═══ Messages 注入（每轮调用，去重，实时反映 state 变化）═══

def inject_env(messages: list[dict], state: SessionState) -> list[dict]:
    """注入 <env> 块。每轮调用，去掉旧的再插新的。空 state 零开销。"""
    if state.is_empty():
        return messages
    env_text = state.render()
    if not env_text:
        return messages
    if not messages:
        return [{"role": "system", "content": env_text}]

    cleaned = [m for m in messages if not (m.get("role") == "system" and "<env>" in m.get("content", ""))]
    if cleaned and cleaned[0].get("role") == "system":
        return [cleaned[0], {"role": "system", "content": env_text}] + cleaned[1:]
    return [{"role": "system", "content": env_text}] + cleaned
