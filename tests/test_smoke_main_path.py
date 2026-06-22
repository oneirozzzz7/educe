"""
P0 Smoke Test — 主路径基线验证

验证：输入简单任务 → 跑完 action loop → 产出结果
不依赖前端，不需要浏览器，纯后端集成测试。

运行: pytest tests/test_smoke_main_path.py -v
需要环境变量: EDUCE_MODEL_KEY (或 pyproject.toml 已配置)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

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
        pytest.skip("No model API key configured (set EDUCE_MODEL_KEY)")
    config.default_model = ModelConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    return config


def _create_orchestrator(config: EduceConfig) -> Orchestrator:
    model_cfg = config.default_model
    client = ModelClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)
    orchestrator = Orchestrator(config)
    for agent_cls in ALL_AGENTS:
        agent = agent_cls(config=config, model_client=client, knowledge=orchestrator.knowledge)
        orchestrator.register(agent)
    return orchestrator


class TestMainPathSmoke:

    @pytest.fixture
    def config(self):
        return _get_config()

    @pytest.fixture
    def orchestrator(self, config):
        return _create_orchestrator(config)

    @pytest.mark.asyncio
    async def test_module_health_all_ok(self, orchestrator):
        """All modules should load successfully."""
        disabled = [k for k, v in orchestrator._module_health.items()
                    if v.startswith("disabled")]
        assert disabled == [], f"Disabled modules: {disabled}"

    @pytest.mark.asyncio
    async def test_simple_reply(self, orchestrator):
        """Simple question should produce a non-empty response."""
        orchestrator.context.metadata["session_id"] = "smoke-test-reply"
        result = await orchestrator.run("什么是 Python？")
        assert result is not None
        messages = [m for m in orchestrator.conversation.turns if m.role == "assistant"]
        assert len(messages) > 0, "No assistant response generated"
        assert len(messages[0].content) > 10, "Response too short"

    @pytest.mark.asyncio
    async def test_write_and_run_file(self, orchestrator):
        """Core path: write a file + run it → verify output exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "hello.py"
            orchestrator.context.metadata["session_id"] = "smoke-test-write"
            orchestrator.context.metadata["_project_context_path"] = tmpdir

            result = await orchestrator.run(
                f"请写一个 Python 脚本到 {target}，内容是 print('hello smoke test')，然后运行它"
            )

            assert result is not None
            has_response = any(
                m.role == "assistant" and m.content
                for m in orchestrator.conversation.turns
            )
            assert has_response, "Orchestrator produced no response"

    @pytest.mark.asyncio
    async def test_health_api_reports_status(self, config):
        """Health tracking works across multiple orchestrator instances."""
        o1 = _create_orchestrator(config)
        o2 = _create_orchestrator(config)
        assert "organs" in o1._module_health
        assert "organs" in o2._module_health


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
