"""
复利记忆系统 — Educe 的核心差异化

"Claude Code 每次从零开始。Educe 带着项目的伤疤工作。"

记忆类型：
- fact: 当前世界状态（可衰减、可证伪）
- scar: 历史教训（不衰减、只可结构证伪）
- convention: 约定/规则（高置信、人确认）
- skill: 已编译的操作模式（由 TraceCompiler 生成）
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("educe.memory")

MEMORY_DIR = Path(".educe/memory")


@dataclass
class MemoryEntry:
    id: str
    type: str                    # fact | scar | convention | skill
    content: str                 # 人可读描述
    confidence: float = 0.7
    scope: str = ""              # 适用范围（目录/模块）
    tags: list[str] = field(default_factory=list)
    anchor: dict | None = None   # {"type": "file", "ref": "path", "fingerprint": "..."}
    provenance: dict = field(default_factory=lambda: {"born": "", "confirmed": [], "challenged": []})
    verified_at: float = 0
    related: list[str] = field(default_factory=list)
    status: str = "active"       # active | disputed | archived

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "confidence": self.confidence,
            "scope": self.scope,
            "tags": self.tags,
            "anchor": self.anchor,
            "provenance": self.provenance,
            "verified_at": self.verified_at,
            "related": self.related,
        }
        if self.status != "active":
            d["status"] = self.status
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(
            id=d["id"],
            type=d.get("type", "fact"),
            content=d.get("content", ""),
            confidence=d.get("confidence", 0.7),
            scope=d.get("scope", ""),
            tags=d.get("tags", []),
            anchor=d.get("anchor"),
            provenance=d.get("provenance", {"born": "", "confirmed": [], "challenged": []}),
            verified_at=d.get("verified_at", 0),
            related=d.get("related", []),
            status=d.get("status", "active"),
        )


# ═══ 记忆衰减策略 ═══

DECAY_POLICY = {
    "fact": 0.01,       # 每天 -0.01
    "scar": 0.0,        # 不衰减
    "convention": 0.002, # 极慢衰减
    "skill": 0.005,     # 慢衰减
}

CONFIDENCE_THRESHOLD = 0.3  # 低于此值的记忆不注入


# ═══ MemoryStore ═══

class ProjectMemoryStore:
    """项目记忆存储"""

    def __init__(self, base_dir: Path | None = None):
        self._dir = base_dir or MEMORY_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "project_memory.jsonl"
        self._entries: list[MemoryEntry] = []
        self._load()

    def _load(self):
        if self._file.exists():
            self._entries = []
            for line in self._file.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    try:
                        self._entries.append(MemoryEntry.from_dict(json.loads(line)))
                    except Exception as e:
                        log.debug("suppressed: %s", e)

    def _save(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(e.to_dict(), ensure_ascii=False) for e in self._entries]
        self._file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def add(self, entry: MemoryEntry) -> None:
        self._entries.append(entry)
        self._save()

    def remove(self, mem_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != mem_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    def get_all(self) -> list[MemoryEntry]:
        return self._entries

    def get_active(self) -> list[MemoryEntry]:
        """返回置信度高于阈值的活跃记忆"""
        now = time.time()
        active = []
        for e in self._entries:
            decay = DECAY_POLICY.get(e.type, 0.01)
            days_since_verify = (now - e.verified_at) / 86400 if e.verified_at else 0
            effective_conf = e.confidence - (decay * days_since_verify)
            if effective_conf >= CONFIDENCE_THRESHOLD:
                active.append(e)
        return active

    def build_prompt_injection(self) -> str:
        """构建记忆注入的 system prompt 片段"""
        active = self.get_active()
        if not active:
            return ""

        sections = {"fact": [], "scar": [], "convention": []}
        for e in active:
            if e.status == "disputed":
                continue
            bucket = sections.get(e.type, sections.get("fact"))
            if bucket is not None:
                bucket.append(e)

        parts = []

        if sections["convention"]:
            parts.append("## 项目约定")
            for e in sections["convention"]:
                parts.append(f"- {e.content}")

        if sections["fact"]:
            parts.append("\n## 项目知识")
            for e in sections["fact"]:
                parts.append(f"- {e.content}")

        if sections["scar"]:
            parts.append("\n## 历史教训（曾踩过的坑）")
            for e in sections["scar"]:
                parts.append(f"- ⚠️ {e.content}")

        return "\n".join(parts)

    def find_conflicts(self, new_entry: MemoryEntry) -> list[MemoryEntry]:
        """检测与新记忆可能冲突的已有记忆。

        冲突条件：同 type + 同 scope + 标签有交集 + 内容不同。
        """
        conflicts = []
        new_tags = set(new_entry.tags)
        new_key = new_entry.content[:40].lower().strip()

        for existing in self._entries:
            if existing.status == "archived":
                continue
            if existing.type != new_entry.type:
                continue
            if existing.scope != new_entry.scope:
                continue
            if existing.content == new_entry.content:
                continue
            existing_tags = set(existing.tags)
            if new_tags & existing_tags:
                conflicts.append(existing)
                continue
            existing_key = existing.content[:40].lower().strip()
            if _content_overlap(new_key, existing_key) > 0.5:
                conflicts.append(existing)

        return conflicts

    def mark_disputed(self, entry_ids: list[str]) -> None:
        """将指定记忆标记为 disputed（不注入 prompt，等待仲裁）"""
        for e in self._entries:
            if e.id in entry_ids:
                e.status = "disputed"
                e.provenance.setdefault("challenged", []).append(
                    time.strftime("%Y-%m-%d %H:%M"))
        self._save()

    def resolve_conflict(self, winner_id: str, loser_ids: list[str]) -> None:
        """仲裁结果：winner 提升置信度并恢复 active，loser 归档"""
        for e in self._entries:
            if e.id == winner_id:
                e.status = "active"
                e.confidence = min(1.0, e.confidence + 0.15)
                e.provenance.setdefault("confirmed", []).append(
                    time.strftime("%Y-%m-%d %H:%M"))
                e.verified_at = time.time()
            elif e.id in loser_ids:
                e.status = "archived"
                e.confidence = 0.0
        self._save()

    def get_disputed(self) -> list[MemoryEntry]:
        """返回所有待仲裁的记忆"""
        return [e for e in self._entries if e.status == "disputed"]


def _content_overlap(a: str, b: str) -> float:
    """简单的字符级 Jaccard 相似度"""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0
