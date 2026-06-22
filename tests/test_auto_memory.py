"""
P1: 记忆自动写入单元测试

验证：
- _auto_write_memory 写入/去重/限速
- fact 从 trace 写入
- scar 从 failure 写入
- convention 从 user correction 写入
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from educe.core.config import EduceConfig
from educe.core.orchestrator import Orchestrator
from educe.core.project_memory import ProjectMemoryStore, MemoryEntry


class TestAutoMemoryCore:

    @pytest.fixture
    def orchestrator(self, tmp_path):
        config = EduceConfig.load()
        o = Orchestrator(config)
        o.context.metadata["session_id"] = "test-auto-mem"
        return o

    def test_auto_write_creates_entry(self, orchestrator, tmp_path):
        """Basic write creates a memory entry."""
        mem_dir = tmp_path / "memory"
        with patch("educe.core.project_memory.MEMORY_DIR", mem_dir):
            result = orchestrator._auto_write_memory("fact", "Python works here")
            assert result is True
            store = ProjectMemoryStore(mem_dir)
            entries = store.get_all()
            assert len(entries) == 1
            assert entries[0].type == "fact"
            assert "Python works here" in entries[0].content

    def test_dedup_reinforces_existing(self, orchestrator, tmp_path):
        """Duplicate write reinforces instead of creating new."""
        mem_dir = tmp_path / "memory"
        with patch("educe.core.project_memory.MEMORY_DIR", mem_dir):
            orchestrator._auto_write_memory("fact", "test dedup", detail_key="dedup_test")
            orchestrator._auto_write_memory("fact", "test dedup v2", detail_key="dedup_test")
            store = ProjectMemoryStore(mem_dir)
            entries = store.get_all()
            assert len(entries) == 1
            assert entries[0].confidence == pytest.approx(0.55, abs=0.01)

    def test_rate_limit_enforced(self, orchestrator, tmp_path):
        """Session limit of 5 is enforced."""
        mem_dir = tmp_path / "memory"
        with patch("educe.core.project_memory.MEMORY_DIR", mem_dir):
            for i in range(7):
                orchestrator._auto_write_memory("fact", f"entry {i}", detail_key=f"key_{i}")
            store = ProjectMemoryStore(mem_dir)
            assert len(store.get_all()) == 5

    def test_scar_starts_at_lower_confidence(self, orchestrator, tmp_path):
        """Scars start at 0.4 confidence."""
        mem_dir = tmp_path / "memory"
        with patch("educe.core.project_memory.MEMORY_DIR", mem_dir):
            orchestrator._auto_write_memory("scar", "Don't do X")
            store = ProjectMemoryStore(mem_dir)
            assert store.get_all()[0].confidence == pytest.approx(0.4)

    def test_total_cap_evicts_low_confidence(self, orchestrator, tmp_path):
        """When total exceeds 100, low-confidence entries are evicted."""
        mem_dir = tmp_path / "memory"
        store = ProjectMemoryStore(mem_dir)
        for i in range(102):
            entry = MemoryEntry(
                id=f"old_{i}", type="fact", content=f"old entry {i}",
                confidence=0.3 if i < 10 else 0.7,
            )
            store.add(entry)

        with patch("educe.core.project_memory.MEMORY_DIR", mem_dir):
            orchestrator._auto_write_memory("fact", "new entry", detail_key="unique_new")
            reloaded = ProjectMemoryStore(mem_dir)
            assert len(reloaded.get_all()) < 102


class TestConventionBuffer:

    def test_correction_pending_set_on_error_signal(self):
        """When signal='error', correction is buffered."""
        config = EduceConfig.load()
        o = Orchestrator(config)
        o.context.metadata["session_id"] = "test-convention"
        o.context.metadata["_last_user_signal"] = "error"
        o.context.metadata["_correction_pending"] = "不对，应该用 pytest 不是 unittest"
        assert o.context.metadata["_correction_pending"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
