"""
数据迁移脚本：旧系统 → 统一知识系统

将 knowledge.json + skills/*.json + domain_stats.json 迁移到 .deepforge/unified/

幂等：已存在的 entries 跳过，可安全重复执行。
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from deepforge.core.unified_store import (
    KnowledgeEntry, KnowledgeContent, KnowledgeClassification,
    KnowledgeTriggers, KnowledgeStats, KnowledgeProvenance,
    UnifiedKnowledgeStore,
)


DEEPFORGE_DIR = Path(".deepforge")


def _infer_maturity(usage_count: int, success_count: int) -> str:
    rate = success_count / max(usage_count, 1)
    if usage_count >= 10 and rate > 0.8:
        return "pattern"
    if usage_count >= 3:
        return "experience"
    return "observation"


def _infer_scope(usage_count: int) -> str:
    if usage_count >= 20:
        return "global"
    if usage_count >= 5:
        return "project"
    return "session"


def _extract_domain_prefix(content: str) -> tuple[str, str, str]:
    """从 content 提取 [Domain] 前缀，返回 (domain, category, clean_body)"""
    m = re.match(r'^\[([^\]]+)\]\s*', content)
    if not m:
        return "", "insight", content
    prefix = m.group(1)
    body = content[m.end():]
    if prefix in ("成功",):
        return "tech", "success_pattern", body
    if prefix in ("失败",):
        return "tech", "lesson", body
    if prefix.startswith("build_seed"):
        return "tech", "build_rule", body
    return prefix, "insight", body


def _map_category(old_category: str) -> str:
    mapping = {
        "insight": "insight",
        "fact": "fact",
        "lesson": "lesson",
        "pattern": "build_rule",
        "success": "success_pattern",
        "failure": "lesson",
        "domain_concept": "fact",
        "domain_chain": "insight",
        "domain_pitfall": "pitfall",
    }
    return mapping.get(old_category, "insight")


def migrate_knowledge(store: UnifiedKnowledgeStore, backup_dir: Path):
    """迁移 knowledge.json"""
    src = DEEPFORGE_DIR / "knowledge" / "knowledge.json"
    if not src.exists():
        print("  [skip] knowledge.json not found")
        return 0

    shutil.copy2(str(src), str(backup_dir / "knowledge.json"))
    entries = json.loads(src.read_text(encoding="utf-8"))
    migrated = 0

    for old in entries:
        old_id = old.get("id", "")
        new_id = f"k_{old_id}" if len(old_id) <= 12 else f"k_{old_id[:12]}"
        if (store.entries_dir / f"{new_id}.json").exists():
            continue

        content = old.get("content", "")
        domain, category_from_prefix, body = _extract_domain_prefix(content)
        old_category = old.get("category", "insight")
        category = category_from_prefix if domain else _map_category(old_category)

        usage = old.get("usage_count", 0)
        success = old.get("success_count", 0)

        entry = KnowledgeEntry(
            id=new_id,
            version=1,
            created_at=old.get("last_used", time.time()) - 86400,
            updated_at=old.get("last_used", time.time()),
            content=KnowledgeContent(body=body),
            maturity=_infer_maturity(usage, success),
            scope=_infer_scope(usage),
            source="migration",
            classification=KnowledgeClassification(
                domain=domain, category=category, tags=[]),
            triggers=KnowledgeTriggers(
                tokens=list(old.get("triggers", []))[:20],
                conditions=[]),
            stats=KnowledgeStats(
                usage_count=usage,
                success_count=success,
                failure_count=max(0, usage - success),
                last_used=old.get("last_used", 0),
                streak=0),
            provenance=KnowledgeProvenance(origin_type="migration"),
        )
        store._write_entry(entry)
        store._add_to_catalog(entry)
        migrated += 1

    print(f"  [done] knowledge: {migrated} entries migrated")
    return migrated


def migrate_skills(store: UnifiedKnowledgeStore, backup_dir: Path):
    """迁移 skills/*.json"""
    skills_dir = DEEPFORGE_DIR / "skills"
    if not skills_dir.exists():
        print("  [skip] skills/ not found")
        return 0

    backup_skills = backup_dir / "skills"
    backup_skills.mkdir(exist_ok=True)

    migrated = 0
    for path in skills_dir.glob("*.json"):
        shutil.copy2(str(path), str(backup_skills / path.name))
        skill = json.loads(path.read_text(encoding="utf-8"))

        name = skill.get("name", path.stem)
        new_id = f"k_skill_{uuid.uuid4().hex[:6]}"
        if (store.entries_dir / f"{new_id}.json").exists():
            continue

        entry = KnowledgeEntry(
            id=new_id,
            version=1,
            created_at=time.time(),
            updated_at=time.time(),
            content=KnowledgeContent(
                body=skill.get("description", name),
                prompt_template=skill.get("prompt_template") or None),
            maturity="template",
            scope="global",
            source=skill.get("source", "auto"),
            classification=KnowledgeClassification(
                domain="tech", category="skill",
                tags=skill.get("tags", [])),
            triggers=KnowledgeTriggers(
                tokens=skill.get("tags", []),
                conditions=[{"type": "task_type", "value": "build"}]),
            stats=KnowledgeStats(
                usage_count=skill.get("usage_count", 0),
                success_count=int(skill.get("usage_count", 0) * skill.get("success_rate", 0)),
            ),
            provenance=KnowledgeProvenance(origin_type="migration"),
        )
        store._write_entry(entry)
        store._add_to_catalog(entry)
        migrated += 1

    print(f"  [done] skills: {migrated} entries migrated")
    return migrated


def migrate_seeds(store: UnifiedKnowledgeStore, backup_dir: Path):
    """从 domain_stats.json + activation_engine 默认值创建 seed 文件"""
    stats_path = DEEPFORGE_DIR / "feedback" / "domain_stats.json"

    # Build seed (from activation_engine DEFAULT_BUILD_SEED)
    build_seed_path = store.seeds_dir / "seed_build_general.json"
    if not build_seed_path.exists():
        from deepforge.core.activation_engine import DEFAULT_BUILD_SEED
        store.update_seed("seed_build_general", DEFAULT_BUILD_SEED, "migration_init")

    # Activation seeds from domain_stats
    if stats_path.exists():
        shutil.copy2(str(stats_path), str(backup_dir / "domain_stats.json"))
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        created = 0
        for domain, data in stats.items():
            seed_id = f"seed_activation_{domain}"
            seed_path = store.seeds_dir / f"{seed_id}.json"
            if seed_path.exists():
                continue
            best_seed = data.get("best_seed", "")
            if not best_seed:
                continue
            seed = {
                "id": seed_id,
                "type": "activation",
                "domain": domain,
                "current": {
                    "version": 1,
                    "text": best_seed,
                    "activated_at": data.get("last_updated", time.time()),
                    "performance": {
                        "uses": data.get("total_responses", 0),
                        "avg_quality": data.get("avg_quality", 0),
                    },
                },
                "history": [],
                "ab_test": {
                    "active": False, "candidate": None,
                    "target_uses": 20, "current_uses": 0,
                    "results": {"candidate_wins": 0, "current_wins": 0},
                },
            }
            seed_path.write_text(
                json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
            store._seeds[seed_id] = {"version": 1, "domain": domain}
            created += 1
        print(f"  [done] seeds: {created} domain seeds + 1 build seed")
    else:
        print("  [done] seeds: 1 build seed (no domain_stats.json)")


def run_migration():
    """执行完整迁移"""
    print("=== 统一知识系统迁移 ===\n")

    unified_dir = DEEPFORGE_DIR / "unified"
    backup_dir = DEEPFORGE_DIR / "_migration" / "pre_migration_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    store = UnifiedKnowledgeStore(unified_dir)

    print("[1/4] 迁移 knowledge.json...")
    k_count = migrate_knowledge(store, backup_dir)

    print("[2/4] 迁移 skills...")
    s_count = migrate_skills(store, backup_dir)

    print("[3/4] 迁移 seeds...")
    migrate_seeds(store, backup_dir)

    print("[4/4] 构建 catalog...")
    store._save_catalog()
    store.get_l1_compiled()

    # 写迁移日志
    log = {
        "timestamp": time.time(),
        "knowledge_migrated": k_count,
        "skills_migrated": s_count,
        "total_entries": len(store._catalog),
        "status": "complete",
    }
    (DEEPFORGE_DIR / "_migration" / "migration_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== 迁移完成 ===")
    print(f"  总条目: {len(store._catalog)}")
    print(f"  Seeds: {len(list(store.seeds_dir.glob('seed_*.json')))} 个")
    print(f"  备份: {backup_dir}")


if __name__ == "__main__":
    run_migration()
