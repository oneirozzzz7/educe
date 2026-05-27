from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    id: str
    category: str  # skill, pattern, feedback, project, user
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    usage_count: int = 0
    success_rate: float = 0.0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    source: str = "system"  # system, user, community
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryStore:
    def __init__(self, storage_dir: str = ".deepforge/memory"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    def _index_path(self) -> Path:
        return self.storage_dir / "index.json"

    def _load(self) -> None:
        index_path = self._index_path()
        if not index_path.exists():
            return
        with open(index_path) as f:
            data = json.load(f)
        for entry_data in data:
            entry = MemoryEntry.model_validate(entry_data)
            self._entries[entry.id] = entry

    def _save(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        with open(self._index_path(), "w") as f:
            json.dump([e.model_dump() for e in self._entries.values()], f, ensure_ascii=False, indent=2)

    def add(self, entry: MemoryEntry) -> None:
        self._entries[entry.id] = entry
        self._save()

    def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def search(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        results = []
        query_lower = query.lower()
        for entry in self._entries.values():
            if category and entry.category != category:
                continue
            score = 0
            if query_lower in entry.title.lower():
                score += 3
            if query_lower in entry.content.lower():
                score += 2
            if any(query_lower in tag.lower() for tag in entry.tags):
                score += 1
            if score > 0:
                results.append((score, entry))

        results.sort(key=lambda x: (-x[0], -x[1].usage_count))
        return [e for _, e in results[:limit]]

    def search_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryEntry]:
        tag_set = set(t.lower() for t in tags)
        results = []
        for entry in self._entries.values():
            overlap = len(tag_set & set(t.lower() for t in entry.tags))
            if overlap > 0:
                results.append((overlap, entry))
        results.sort(key=lambda x: (-x[0], -x[1].usage_count))
        return [e for _, e in results[:limit]]

    def update_usage(self, entry_id: str, success: bool = True) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        entry.usage_count += 1
        total = entry.usage_count
        entry.success_rate = ((entry.success_rate * (total - 1)) + (1.0 if success else 0.0)) / total
        entry.updated_at = time.time()
        self._save()

    def remove(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    def list_all(self, category: str | None = None) -> list[MemoryEntry]:
        entries = list(self._entries.values())
        if category:
            entries = [e for e in entries if e.category == category]
        return sorted(entries, key=lambda e: -e.updated_at)

    def stats(self) -> dict[str, Any]:
        categories: dict[str, int] = {}
        for entry in self._entries.values():
            categories[entry.category] = categories.get(entry.category, 0) + 1
        return {
            "total": len(self._entries),
            "categories": categories,
        }
