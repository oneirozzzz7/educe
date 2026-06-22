"""
P0-3: Module Failure Isolation Test

Verifies: if non-core modules (VerbosityOrgan, DomainEngine, etc.) throw on init,
the orchestrator still starts and the main path still works.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from educe.core.config import EduceConfig, ModelConfig
from educe.core.orchestrator import Orchestrator
from educe.models.router import ModelClient
from educe.agents import ALL_AGENTS


def _get_config() -> EduceConfig:
    config = EduceConfig.load()
    api_key = os.environ.get("EDUCE_MODEL_KEY") or config.default_model.api_key
    base_url = os.environ.get("EDUCE_MODEL_URL") or config.default_model.base_url
    model = os.environ.get("EDUCE_MODEL_NAME") or config.default_model.model
    if not api_key:
        pytest.skip("No model API key configured")
    config.default_model = ModelConfig(model=model, api_key=api_key, base_url=base_url)
    return config


class TestModuleIsolation:

    def test_organ_init_failure_isolated(self):
        """VerbosityOrgan raising should not prevent orchestrator from starting."""
        config = EduceConfig.load()
        with patch("educe.core.organ_verbosity.VerbosityOrgan.__init__",
                   side_effect=RuntimeError("simulated organ crash")):
            o = Orchestrator(config)
            assert o.verbosity_organ is None
            assert o.organ_registry is None
            assert "organs" in o._module_health
            assert "disabled" in o._module_health["organs"]

    def test_domain_engine_failure_isolated(self):
        """DomainEngine raising should not prevent orchestrator from starting."""
        config = EduceConfig.load()
        with patch("educe.core.domain_engine.DomainEngine.__init__",
                   side_effect=ImportError("simulated missing dep")):
            o = Orchestrator(config)
            assert o.domain_engine is None
            assert "disabled" in o._module_health["domain_engine"]
            assert o.activation_engine is not None or "disabled" in o._module_health.get("activation_engine", "ok")

    def test_unified_store_failure_isolated(self):
        """UnifiedKnowledgeStore raising should not crash init."""
        config = EduceConfig.load()
        with patch("educe.core.unified_store.UnifiedKnowledgeStore.__init__",
                   side_effect=PermissionError("simulated fs error")):
            o = Orchestrator(config)
            assert o.unified_store is None
            assert "disabled" in o._module_health["unified_store"]

    def test_multiple_module_failures_still_starts(self):
        """Even with 3+ modules crashing, orchestrator init succeeds."""
        config = EduceConfig.load()
        with patch("educe.core.organ_verbosity.VerbosityOrgan.__init__",
                   side_effect=RuntimeError("organ crash")), \
             patch("educe.core.domain_engine.DomainEngine.__init__",
                   side_effect=RuntimeError("domain crash")), \
             patch("educe.core.unified_store.UnifiedKnowledgeStore.__init__",
                   side_effect=RuntimeError("store crash")):
            o = Orchestrator(config)
            disabled = [k for k, v in o._module_health.items() if v.startswith("disabled")]
            assert len(disabled) >= 3
            assert o.conversation is not None
            assert o.streaming_registry is not None

    @pytest.mark.asyncio
    async def test_main_path_works_with_organs_disabled(self):
        """Core path (simple reply) works even with organs disabled."""
        config = _get_config()
        with patch("educe.core.organ_verbosity.VerbosityOrgan.__init__",
                   side_effect=RuntimeError("organ crash")):
            model_cfg = config.default_model
            client = ModelClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)
            o = Orchestrator(config)
            for agent_cls in ALL_AGENTS:
                agent = agent_cls(config=config, model_client=client, knowledge=o.knowledge)
                o.register(agent)

            o.context.metadata["session_id"] = "isolation-test"
            result = await o.run("1+1等于几？")
            assert result is not None
            messages = [m for m in o.conversation.turns if m.role == "assistant"]
            assert len(messages) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
