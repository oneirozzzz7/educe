"""
统一知识系统（Unified Knowledge Store）

替代 LayeredCache + SkillRegistry + DomainEngine 的统一知识存储层。
每条知识有成熟度连续谱（observation → experience → pattern → template），
scope 可演化（session → project → global），所有变更有版本历史。

recall 完全由模型判断相关性，不做 trigger_index。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Awaitable


@dataclass
class KnowledgeContent:
    body: str
    prompt_template: str | None = None
    reasoning_chain: list[str] | None = None


@dataclass
class KnowledgeClassification:
    domain: str = ""
    category: str = "insight"
    tags: list[str] = field(default_factory=list)


@dataclass
class KnowledgeTriggers:
    tokens: list[str] = field(default_factory=list)
    conditions: list[dict] = field(default_factory=list)


@dataclass
class KnowledgeStats:
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_used: float = 0.0
    streak: int = 0


@dataclass
class KnowledgeProvenance:
    origin_session: str = ""
    origin_type: str = "auto"
    parent_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class KnowledgeEntry:
    id: str
    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    content: KnowledgeContent = field(default_factory=lambda: KnowledgeContent(body=""))
    maturity: str = "observation"
    scope: str = "session"
    source: str = "auto"
    classification: KnowledgeClassification = field(default_factory=KnowledgeClassification)
    triggers: KnowledgeTriggers = field(default_factory=KnowledgeTriggers)
    stats: KnowledgeStats = field(default_factory=KnowledgeStats)
    provenance: KnowledgeProvenance = field(default_factory=KnowledgeProvenance)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeEntry":
        return cls(
            id=d["id"],
            version=d.get("version", 1),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
            content=KnowledgeContent(**d.get("content", {"body": ""})),
            maturity=d.get("maturity", "observation"),
            scope=d.get("scope", "session"),
            source=d.get("source", "auto"),
            classification=KnowledgeClassification(**d.get("classification", {})),
            triggers=KnowledgeTriggers(**d.get("triggers", {})),
            stats=KnowledgeStats(**d.get("stats", {})),
            provenance=KnowledgeProvenance(**d.get("provenance", {})),
        )

    @property
    def preview(self) -> str:
        return self.content.body[:80]

    @property
    def success_rate(self) -> float:
        total = self.stats.usage_count
        if total == 0:
            return 0.0
        return self.stats.success_count / total


def _gen_id() -> str:
    return "k_" + uuid.uuid4().hex[:12]


class UnifiedKnowledgeStore:
    """统一知识存储。recall 由模型判断相关性。"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.entries_dir = base_dir / "entries"
        self.versions_dir = base_dir / "versions"
        self.seeds_dir = base_dir / "seeds"
        self.compiled_dir = base_dir / "compiled"
        self.signals_dir = base_dir.parent / "signals"
        self.evolution_dir = base_dir.parent / "evolution"

        self._catalog: list[dict] = []
        self._seeds: dict[str, dict] = {}
        self._ensure_dirs()
        self._load_catalog()

    def _ensure_dirs(self):
        for d in [self.entries_dir, self.versions_dir, self.seeds_dir,
                  self.compiled_dir, self.signals_dir, self.evolution_dir / "records"]:
            d.mkdir(parents=True, exist_ok=True)

    def _catalog_path(self) -> Path:
        return self.base_dir / "catalog.json"

    def _load_catalog(self):
        path = self._catalog_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._catalog = data.get("entries", [])
            self._seeds = data.get("seeds", {})
        else:
            self._catalog = []
            self._seeds = {}

    def _save_catalog(self):
        data = {
            "entries": self._catalog,
            "seeds": self._seeds,
            "stats": {"total": len(self._catalog), "last_rebuilt": time.time()},
        }
        self._catalog_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ═══════════════════════════════════════
    #  写入
    # ═══════════════════════════════════════

    def add(self, content: str, source: str = "auto", maturity: str = "observation",
            scope: str = "session", category: str = "insight", domain: str = "",
            tags: list[str] | None = None, conditions: list[dict] | None = None,
            prompt_template: str | None = None, session_id: str = "") -> str:
        entry = KnowledgeEntry(
            id=_gen_id(),
            content=KnowledgeContent(body=content, prompt_template=prompt_template),
            maturity=maturity,
            scope=scope,
            source=source,
            classification=KnowledgeClassification(
                domain=domain, category=category, tags=tags or []),
            triggers=KnowledgeTriggers(conditions=conditions or []),
            provenance=KnowledgeProvenance(
                origin_session=session_id, origin_type=source),
        )
        self._write_entry(entry)
        self._add_to_catalog(entry)
        self._save_catalog()
        self._invalidate_compiled()
        return entry.id

    def update(self, entry_id: str, **changes) -> int:
        entry = self.get_entry(entry_id)
        if not entry:
            return -1
        self._save_version(entry)
        entry.version += 1
        entry.updated_at = time.time()
        for key, value in changes.items():
            if key == "body":
                entry.content.body = value
            elif key == "maturity":
                entry.maturity = value
            elif key == "scope":
                entry.scope = value
            elif key == "prompt_template":
                entry.content.prompt_template = value
            elif key == "category":
                entry.classification.category = value
            elif key == "tags":
                entry.classification.tags = value
            elif key == "conditions":
                entry.triggers.conditions = value
        self._write_entry(entry)
        self._update_catalog_entry(entry)
        self._save_catalog()
        return entry.version

    def record_usage(self, entry_id: str, success: bool):
        entry = self.get_entry(entry_id)
        if not entry:
            return
        entry.stats.usage_count += 1
        entry.stats.last_used = time.time()
        if success:
            entry.stats.success_count += 1
            entry.stats.streak += 1
        else:
            entry.stats.failure_count += 1
            entry.stats.streak = 0
        entry.updated_at = time.time()

        # 成熟度自然升级（模型数据驱动，不硬编码阈值——使用统计作为信号）
        new_maturity = self._evaluate_maturity(entry)
        if new_maturity != entry.maturity:
            self._save_version(entry)
            entry.version += 1
            entry.maturity = new_maturity

        self._write_entry(entry)
        self._update_catalog_entry(entry)
        self._save_catalog()
        self._invalidate_compiled()

    def _evaluate_maturity(self, entry: "KnowledgeEntry") -> str:
        """根据使用统计评估成熟度——数据驱动的自然升降"""
        rate = entry.success_rate
        usage = entry.stats.usage_count
        streak = entry.stats.streak

        if entry.maturity == "observation":
            if usage >= 3 and rate > 0.6:
                return "experience"
        elif entry.maturity == "experience":
            if usage >= 8 and rate > 0.8 and streak >= 3:
                return "pattern"
            if usage >= 5 and rate < 0.3:
                return "observation"
        elif entry.maturity == "pattern":
            if usage >= 5 and rate < 0.4:
                return "experience"

        return entry.maturity

    # ═══════════════════════════════════════
    #  检索（纯模型判断）
    # ═══════════════════════════════════════

    async def recall(self, query: str, model_fn: Callable[[list[dict]], Awaitable[str]],
                     scope: str | None = None, max_results: int = 10) -> list[KnowledgeEntry]:
        candidates = self._get_candidates(scope)
        if not candidates:
            return []
        numbered = "\n".join(
            f"{i+1}. [{c['domain'] or '通用'}|{c['category']}] {c['preview']}"
            for i, c in enumerate(candidates)
        )
        prompt = (
            "从以下知识条目中，选出与用户当前任务直接相关的（对完成任务有帮助的经验/规则/模式）。\n"
            "只输出相关条目的编号（逗号分隔），都不相关则输出 none。\n\n"
            f"用户任务：{query}\n\n"
            f"知识条目：\n{numbered}"
        )
        try:
            result = await model_fn([
                {"role": "system", "content": "你是知识相关性判断助手。只输出编号或none。"},
                {"role": "user", "content": prompt},
            ])
            if "none" in result.lower():
                return []
            import re
            nums = [int(n) for n in re.findall(r'\d+', result)]
            selected_ids = [candidates[n-1]["id"] for n in nums
                           if 1 <= n <= len(candidates)]
            entries = [self.get_entry(eid) for eid in selected_ids[:max_results]]
            return [e for e in entries if e is not None]
        except Exception:
            return []

    def _get_candidates(self, scope: str | None = None, max_candidates: int = 100) -> list[dict]:
        if scope:
            pool = [e for e in self._catalog if e["scope"] == scope or e["scope"] == "global"]
        else:
            pool = list(self._catalog)
        if len(pool) <= max_candidates:
            return pool
        pool.sort(key=lambda x: (
            {"template": 4, "pattern": 3, "experience": 2, "observation": 1}.get(x["maturity"], 0),
            x["usage_count"] * x["success_rate"],
        ), reverse=True)
        return pool[:max_candidates]

    def get_entry(self, entry_id: str) -> KnowledgeEntry | None:
        path = self.entries_dir / f"{entry_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return KnowledgeEntry.from_dict(data)

    def get_l1_compiled(self) -> list[str]:
        compiled_path = self.compiled_dir / "l1_hot.json"
        if compiled_path.exists():
            return json.loads(compiled_path.read_text(encoding="utf-8"))
        hot = [e for e in self._catalog
               if e["maturity"] in ("pattern", "template")
               and e["success_rate"] > 0.8
               and e["usage_count"] >= 5]
        hot.sort(key=lambda x: x["usage_count"] * x["success_rate"], reverse=True)
        compiled = [e["preview"] for e in hot[:10]]
        compiled_path.write_text(
            json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
        return compiled

    def get_catalog_for_model(self, scope: str | None = None) -> str:
        candidates = self._get_candidates(scope)
        return "\n".join(
            f"- [{c['domain'] or '通用'}] {c['preview']}"
            for c in candidates
        )

    # ═══════════════════════════════════════
    #  Seed 管理
    # ═══════════════════════════════════════

    def get_seed(self, seed_type: str = "build", domain: str = "general") -> dict | None:
        seed_id = f"seed_{seed_type}_{domain}"
        path = self.seeds_dir / f"{seed_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        fallback_id = f"seed_{seed_type}_general"
        fallback_path = self.seeds_dir / f"{fallback_id}.json"
        if fallback_path.exists():
            return json.loads(fallback_path.read_text(encoding="utf-8"))
        return None

    def get_seed_text(self, seed_type: str = "build", domain: str = "general") -> str:
        seed = self.get_seed(seed_type, domain)
        if seed and "current" in seed:
            return seed["current"].get("text", "")
        return ""

    def record_seed_use(self, seed_type: str = "build", domain: str = "general"):
        """记录 seed 被使用一次"""
        seed_id = f"seed_{seed_type}_{domain}"
        path = self.seeds_dir / f"{seed_id}.json"
        if not path.exists():
            seed_id = f"seed_{seed_type}_general"
            path = self.seeds_dir / f"{seed_id}.json"
        if not path.exists():
            return
        seed = json.loads(path.read_text(encoding="utf-8"))
        seed["current"]["performance"]["uses"] = seed["current"]["performance"].get("uses", 0) + 1
        path.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")

    def update_seed(self, seed_id: str, new_text: str, reason: str = "") -> int:
        path = self.seeds_dir / f"{seed_id}.json"
        if path.exists():
            seed = json.loads(path.read_text(encoding="utf-8"))
        else:
            parts = seed_id.replace("seed_", "").split("_", 1)
            seed = {
                "id": seed_id,
                "type": parts[0] if parts else "build",
                "domain": parts[1] if len(parts) > 1 else "general",
                "current": {"version": 0, "text": "", "activated_at": 0, "performance": {}},
                "history": [],
                "ab_test": {"active": False, "candidate": None,
                           "target_uses": 20, "current_uses": 0,
                           "results": {"candidate_wins": 0, "current_wins": 0}},
            }
        old_current = seed["current"]
        if old_current.get("text"):
            seed["history"].append({
                **old_current,
                "retired_at": time.time(),
                "retired_reason": reason or "replaced",
            })
        new_version = old_current.get("version", 0) + 1
        seed["current"] = {
            "version": new_version,
            "text": new_text,
            "activated_at": time.time(),
            "performance": {"uses": 0, "avg_quality": 0.0},
        }
        path.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
        self._seeds[seed_id] = {"version": new_version, "domain": seed["domain"]}
        self._save_catalog()
        return new_version

    # ═══════════════════════════════════════
    #  信号 & 进化记录
    # ═══════════════════════════════════════

    def record_signal(self, signal: dict):
        now = time.localtime()
        month_dir = self.signals_dir / f"{now.tm_year}-{now.tm_mon:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)
        day_file = month_dir / f"sig_{now.tm_year}{now.tm_mon:02d}{now.tm_mday:02d}.jsonl"
        if "id" not in signal:
            signal["id"] = f"sig_{now.tm_year}{now.tm_mon:02d}{now.tm_mday:02d}_{uuid.uuid4().hex[:6]}"
        if "timestamp" not in signal:
            signal["timestamp"] = time.time()
        with open(day_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(signal, ensure_ascii=False) + "\n")

    def add_evolution_record(self, record: dict):
        now = time.localtime()
        records_dir = self.evolution_dir / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        day_file = records_dir / f"ev_{now.tm_year}{now.tm_mon:02d}{now.tm_mday:02d}.jsonl"
        if "id" not in record:
            record["id"] = f"ev_{now.tm_year}{now.tm_mon:02d}{now.tm_mday:02d}_{uuid.uuid4().hex[:6]}"
        if "timestamp" not in record:
            record["timestamp"] = time.time()
        with open(day_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ═══════════════════════════════════════
    #  内部方法
    # ═══════════════════════════════════════

    def _write_entry(self, entry: KnowledgeEntry):
        path = self.entries_dir / f"{entry.id}.json"
        path.write_text(
            json.dumps(entry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _invalidate_compiled(self):
        compiled_path = self.compiled_dir / "l1_hot.json"
        if compiled_path.exists():
            compiled_path.unlink()

    def _save_version(self, entry: KnowledgeEntry):
        ver_dir = self.versions_dir / entry.id
        ver_dir.mkdir(parents=True, exist_ok=True)
        ver_path = ver_dir / f"v{entry.version}.json"
        ver_path.write_text(
            json.dumps(entry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _add_to_catalog(self, entry: KnowledgeEntry):
        self._catalog.append({
            "id": entry.id,
            "preview": entry.preview,
            "maturity": entry.maturity,
            "scope": entry.scope,
            "domain": entry.classification.domain,
            "category": entry.classification.category,
            "source": entry.source,
            "usage_count": entry.stats.usage_count,
            "success_rate": entry.success_rate,
        })

    def _update_catalog_entry(self, entry: KnowledgeEntry):
        for i, c in enumerate(self._catalog):
            if c["id"] == entry.id:
                self._catalog[i] = {
                    "id": entry.id,
                    "preview": entry.preview,
                    "maturity": entry.maturity,
                    "scope": entry.scope,
                    "domain": entry.classification.domain,
                    "category": entry.classification.category,
                    "source": entry.source,
                    "usage_count": entry.stats.usage_count,
                    "success_rate": entry.success_rate,
                }
                return

    def rebuild_catalog(self):
        self._catalog = []
        self._seeds = {}
        for path in self.entries_dir.glob("k_*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = KnowledgeEntry.from_dict(data)
            self._add_to_catalog(entry)
        for path in self.seeds_dir.glob("seed_*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            self._seeds[data["id"]] = {
                "version": data.get("current", {}).get("version", 1),
                "domain": data.get("domain", "general"),
            }
        self._save_catalog()
        # rebuild l1 compiled
        compiled_path = self.compiled_dir / "l1_hot.json"
        if compiled_path.exists():
            compiled_path.unlink()
        self.get_l1_compiled()
