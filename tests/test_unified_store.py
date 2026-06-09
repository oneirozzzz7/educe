"""
统一知识系统单元测试
"""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from deepforge.core.unified_store import UnifiedKnowledgeStore, KnowledgeEntry


@pytest.fixture
def store(tmp_path):
    """创建临时 store 实例"""
    unified_dir = tmp_path / "unified"
    return UnifiedKnowledgeStore(unified_dir)


class TestAdd:
    def test_add_creates_entry_file(self, store):
        entry_id = store.add("表单必须有输入验证", source="user", maturity="pattern")
        assert entry_id.startswith("k_")
        path = store.entries_dir / f"{entry_id}.json"
        assert path.exists()

    def test_add_updates_catalog(self, store):
        entry_id = store.add("深色主题用 #1a1a2e", category="build_rule")
        assert len(store._catalog) == 1
        assert store._catalog[0]["id"] == entry_id
        assert store._catalog[0]["preview"] == "深色主题用 #1a1a2e"

    def test_add_persists_catalog(self, store):
        store.add("测试持久化")
        cat = json.loads(store._catalog_path().read_text())
        assert cat["stats"]["total"] == 1

    def test_add_with_conditions(self, store):
        entry_id = store.add(
            "页面背景用深色",
            source="user", maturity="pattern",
            conditions=[{"type": "task_type", "value": "build"}],
        )
        entry = store.get_entry(entry_id)
        assert entry.triggers.conditions == [{"type": "task_type", "value": "build"}]


class TestUpdate:
    def test_update_increments_version(self, store):
        entry_id = store.add("原始内容")
        new_ver = store.update(entry_id, body="更新后内容")
        assert new_ver == 2
        entry = store.get_entry(entry_id)
        assert entry.content.body == "更新后内容"
        assert entry.version == 2

    def test_update_saves_version_history(self, store):
        entry_id = store.add("v1内容")
        store.update(entry_id, body="v2内容")
        ver_dir = store.versions_dir / entry_id
        assert (ver_dir / "v1.json").exists()
        v1 = json.loads((ver_dir / "v1.json").read_text())
        assert v1["content"]["body"] == "v1内容"

    def test_update_nonexistent_returns_minus_one(self, store):
        result = store.update("k_nonexistent", body="test")
        assert result == -1


class TestRecall:
    @pytest.mark.asyncio
    async def test_recall_with_model_fn(self, store):
        store.add("ECharts 从 CDN 引入做图表", domain="tech")
        store.add("表单间距用 8px 递增", domain="tech")
        store.add("用户喜欢深色主题", domain="design")

        async def mock_model(messages):
            return "1, 2"

        results = await store.recall("做一个数据可视化页面", mock_model)
        assert len(results) == 2
        assert results[0].content.body == "ECharts 从 CDN 引入做图表"

    @pytest.mark.asyncio
    async def test_recall_none_returns_empty(self, store):
        store.add("某条知识")

        async def mock_model(messages):
            return "none"

        results = await store.recall("完全不相关的查询", mock_model)
        assert results == []

    @pytest.mark.asyncio
    async def test_recall_empty_store(self, store):
        async def mock_model(messages):
            return "1"

        results = await store.recall("任何查询", mock_model)
        assert results == []

    @pytest.mark.asyncio
    async def test_recall_model_error_returns_empty(self, store):
        store.add("某条知识")

        async def broken_model(messages):
            raise RuntimeError("模型挂了")

        results = await store.recall("查询", broken_model)
        assert results == []


class TestRecordUsage:
    def test_success_increments_stats(self, store):
        entry_id = store.add("测试知识")
        store.record_usage(entry_id, success=True)
        entry = store.get_entry(entry_id)
        assert entry.stats.usage_count == 1
        assert entry.stats.success_count == 1
        assert entry.stats.streak == 1

    def test_failure_resets_streak(self, store):
        entry_id = store.add("测试知识")
        store.record_usage(entry_id, success=True)
        store.record_usage(entry_id, success=True)
        store.record_usage(entry_id, success=False)
        entry = store.get_entry(entry_id)
        assert entry.stats.streak == 0
        assert entry.stats.failure_count == 1

    def test_usage_updates_catalog(self, store):
        entry_id = store.add("测试知识")
        store.record_usage(entry_id, success=True)
        cat_entry = next(e for e in store._catalog if e["id"] == entry_id)
        assert cat_entry["usage_count"] == 1


class TestSeed:
    def test_get_seed_nonexistent_returns_none(self, store):
        assert store.get_seed("build", "nonexistent") is None

    def test_update_and_get_seed(self, store):
        ver = store.update_seed("seed_build_general", "新的激发语", "测试更新")
        assert ver == 1
        seed = store.get_seed("build", "general")
        assert seed["current"]["text"] == "新的激发语"
        assert seed["current"]["version"] == 1

    def test_seed_history_preserved(self, store):
        store.update_seed("seed_build_general", "第一版", "init")
        store.update_seed("seed_build_general", "第二版", "evolution")
        seed = store.get_seed("build", "general")
        assert seed["current"]["text"] == "第二版"
        assert len(seed["history"]) == 1
        assert seed["history"][0]["text"] == "第一版"

    def test_get_seed_text(self, store):
        store.update_seed("seed_build_general", "激发内容", "test")
        text = store.get_seed_text("build", "general")
        assert text == "激发内容"

    def test_get_seed_fallback_to_general(self, store):
        store.update_seed("seed_build_general", "通用激发", "test")
        seed = store.get_seed("build", "某个不存在的领域")
        assert seed["current"]["text"] == "通用激发"


class TestSignalAndEvolution:
    def test_record_signal_creates_jsonl(self, store):
        store.record_signal({"type": "build", "session_id": "test123"})
        import os
        signal_files = list(store.signals_dir.rglob("sig_*.jsonl"))
        assert len(signal_files) == 1
        content = signal_files[0].read_text()
        record = json.loads(content.strip())
        assert record["session_id"] == "test123"
        assert "id" in record
        assert "timestamp" in record

    def test_record_signal_appends(self, store):
        store.record_signal({"type": "build", "n": 1})
        store.record_signal({"type": "build", "n": 2})
        signal_files = list(store.signals_dir.rglob("sig_*.jsonl"))
        lines = signal_files[0].read_text().strip().split("\n")
        assert len(lines) == 2

    def test_add_evolution_record(self, store):
        store.add_evolution_record({
            "type": "seed_mutation",
            "subject": {"id": "seed_build_general"},
            "mutation": {"before": "old", "after": "new"},
        })
        ev_files = list((store.evolution_dir / "records").rglob("ev_*.jsonl"))
        assert len(ev_files) == 1
        record = json.loads(ev_files[0].read_text().strip())
        assert record["type"] == "seed_mutation"


class TestRebuildCatalog:
    def test_rebuild_from_disk(self, store):
        store.add("知识A", domain="tech")
        store.add("知识B", domain="design")
        store.update_seed("seed_build_general", "test seed", "init")

        store._catalog = []
        store._seeds = {}
        store.rebuild_catalog()

        assert len(store._catalog) == 2
        assert "seed_build_general" in store._seeds


class TestL1Compiled:
    def test_l1_compiled_filters_by_maturity(self, store):
        store.add("低成熟度", maturity="observation")
        entry_id = store.add("高成熟度高频", maturity="pattern", domain="tech")
        entry = store.get_entry(entry_id)
        entry.stats.usage_count = 10
        entry.stats.success_count = 9
        store._write_entry(entry)
        store._update_catalog_entry(entry)
        store._save_catalog()

        compiled = store.get_l1_compiled()
        assert "高成熟度高频" in compiled[0]
        assert len(compiled) == 1
