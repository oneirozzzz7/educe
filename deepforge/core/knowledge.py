"""
DeepForge 分层缓存召回系统
比Claude Code更轻量（不需200K context），比RAG更准确（不依赖embedding阈值）

核心思想：写入时建索引 + 缓存分层 + 热知识编译进prompt
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class KnowledgeEntry:
    """知识条目——写入时就带好索引"""
    def __init__(self, id: str, content: str, triggers: set[str], category: str = "pattern",
                 usage_count: int = 0, success_count: int = 0, last_used: float = 0):
        self.id = id
        self.content = content
        self.triggers = triggers  # 触发词集合（含别名）
        self.category = category
        self.usage_count = usage_count
        self.success_count = success_count
        self.last_used = last_used

    @property
    def success_rate(self) -> float:
        return self.success_count / max(self.usage_count, 1)

    @property
    def is_hot(self) -> bool:
        """最近7天使用过且成功率>80%"""
        recent = (time.time() - self.last_used) < 7 * 86400
        return recent and self.success_rate > 0.8 and self.usage_count >= 2

    def to_dict(self) -> dict:
        return {
            "id": self.id, "content": self.content,
            "triggers": list(self.triggers), "category": self.category,
            "usage_count": self.usage_count, "success_count": self.success_count,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KnowledgeEntry:
        return cls(
            id=d["id"], content=d["content"],
            triggers=set(d.get("triggers", [])), category=d.get("category", "pattern"),
            usage_count=d.get("usage_count", 0), success_count=d.get("success_count", 0),
            last_used=d.get("last_used", 0),
        )


class LayeredCache:
    """
    四层缓存：
    L1: 编译层——高频成功模式直接内嵌（零成本）
    L2: 热缓存——最近使用过的高成功率条目
    L3: 索引层——全量条目按触发词匹配
    L4: 全文层——LLM辅助搜索（只在L1-L3 miss且卡住时用）
    """

    def __init__(self, storage_dir: str = ".deepforge/knowledge"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, KnowledgeEntry] = {}
        self._compiled_l1: list[str] = []  # 编译进prompt的内容
        self._trigger_index: dict[str, list[str]] = {}  # trigger → [entry_ids]
        self._load()

    def _load(self):
        index_path = self.storage_dir / "knowledge.json"
        if index_path.exists():
            data = json.loads(index_path.read_text())
            for d in data:
                entry = KnowledgeEntry.from_dict(d)
                self._entries[entry.id] = entry
            self._rebuild_index()
            self._compile_l1()

    def _save(self):
        index_path = self.storage_dir / "knowledge.json"
        data = [e.to_dict() for e in self._entries.values()]
        index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _rebuild_index(self):
        """重建触发词倒排索引"""
        self._trigger_index.clear()
        for entry in self._entries.values():
            for trigger in entry.triggers:
                if trigger not in self._trigger_index:
                    self._trigger_index[trigger] = []
                self._trigger_index[trigger].append(entry.id)

    def _compile_l1(self):
        """把高频成功模式编译为prompt片段"""
        hot = sorted(
            [e for e in self._entries.values() if e.usage_count >= 5 and e.success_rate >= 0.8],
            key=lambda e: -e.usage_count
        )[:10]
        self._compiled_l1 = [e.content[:100] for e in hot]

    # ═══ 写入 ═══

    def add(self, content: str, triggers: set[str], category: str = "pattern") -> str:
        """写入知识——自动建索引"""
        import uuid
        id = uuid.uuid4().hex[:10]
        entry = KnowledgeEntry(id=id, content=content, triggers=triggers, category=category)
        self._entries[id] = entry

        for trigger in triggers:
            if trigger not in self._trigger_index:
                self._trigger_index[trigger] = []
            self._trigger_index[trigger].append(id)

        self._save()
        return id

    # ═══ 召回（分层） ═══

    def recall(self, query: str, max_results: int = 5) -> list[str]:
        """分层召回——L1→L2→L3，渐进精确"""
        results = []

        # L1: 编译层（零成本，直接返回）
        # L1内容已编译进prompt，这里不需要返回

        # L2: 热缓存
        hot_entries = [e for e in self._entries.values() if e.is_hot]
        for entry in hot_entries:
            if self._matches(query, entry.triggers):
                results.append(entry.content)
                self._record_use(entry.id)
                if len(results) >= max_results:
                    return results

        # L3: 索引层——触发词匹配
        query_tokens = self._tokenize(query)
        scored: list[tuple[int, KnowledgeEntry]] = []
        for token in query_tokens:
            for entry_id in self._trigger_index.get(token, []):
                entry = self._entries.get(entry_id)
                if entry and entry.content not in results:
                    overlap = len(query_tokens & entry.triggers)
                    scored.append((overlap, entry))

        scored.sort(key=lambda x: (-x[0], -x[1].success_rate))
        for _, entry in scored[:max_results - len(results)]:
            results.append(entry.content)
            self._record_use(entry.id)

        return results

    def get_l1_compiled(self) -> list[str]:
        """获取L1编译层内容——直接注入prompt"""
        return self._compiled_l1

    # ═══ 反馈 ═══

    def record_success(self, entry_id: str):
        if entry_id in self._entries:
            self._entries[entry_id].success_count += 1
            self._save()
            self._compile_l1()  # 可能有新的热知识升级到L1

    def record_failure(self, entry_id: str):
        if entry_id in self._entries:
            self._entries[entry_id].usage_count += 1
            self._save()

    def _record_use(self, entry_id: str):
        if entry_id in self._entries:
            self._entries[entry_id].usage_count += 1
            self._entries[entry_id].last_used = time.time()

    # ═══ 工具 ═══

    def _matches(self, query: str, triggers: set[str]) -> bool:
        query_tokens = self._tokenize(query)
        return bool(query_tokens & triggers)

    def _tokenize(self, text: str) -> set[str]:
        """分词——简单但有效"""
        import re
        # 中文按字符，英文按单词
        cn = set(re.findall(r'[一-鿿]{2,}', text))
        en = set(re.findall(r'[a-zA-Z]{3,}', text.lower()))
        return cn | en

    def stats(self) -> dict:
        return {
            "total": len(self._entries),
            "l1_compiled": len(self._compiled_l1),
            "hot": sum(1 for e in self._entries.values() if e.is_hot),
            "avg_success_rate": sum(e.success_rate for e in self._entries.values()) / max(len(self._entries), 1),
        }
