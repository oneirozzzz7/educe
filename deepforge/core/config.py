from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    provider: str = "openai_compatible"
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    temperature: float = 0.7
    max_tokens: int = 4096


class AgentConfig(BaseModel):
    enabled: bool = True
    model: str | None = None
    max_retries: int = 3
    timeout: int = 120


class MemoryConfig(BaseModel):
    enabled: bool = True
    storage_dir: str = ".deepforge/memory"
    max_entries: int = 10000


class SkillConfig(BaseModel):
    enabled: bool = True
    skill_dir: str = ".deepforge/skills"
    community_dir: str = ".deepforge/community_skills"


class EvolutionConfig(BaseModel):
    enabled: bool = True


class HallucinationGuardConfig(BaseModel):
    enabled: bool = True
    mode: str = "quick"  # "quick"(轻量标注) 或 "deep"(完整声明拆解)


class DeepForgeConfig(BaseModel):
    project_name: str = "DeepForge"
    work_dir: str = "."
    language: str = "zh"

    default_model: ModelConfig = Field(default_factory=ModelConfig)
    models: dict[str, ModelConfig] = Field(default_factory=dict)

    agents: dict[str, AgentConfig] = Field(default_factory=lambda: {
        "project_manager": AgentConfig(),
        "product_manager": AgentConfig(),
        "architect": AgentConfig(),
        "engineer": AgentConfig(),
        "reviewer": AgentConfig(),
        "crowd_user": AgentConfig(),
        "memory_keeper": AgentConfig(),
    })

    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    skills: SkillConfig = Field(default_factory=SkillConfig)
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)
    hallucination_guard: HallucinationGuardConfig = Field(default_factory=HallucinationGuardConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> DeepForgeConfig:
        cls._load_dotenv()

        if path is None:
            candidates = [
                Path.cwd() / "deepforge.yaml",
                Path.cwd() / "deepforge.yml",
                Path.cwd() / ".deepforge" / "config.yaml",
                Path.home() / ".deepforge" / "config.yaml",
            ]
            for candidate in candidates:
                if candidate.exists():
                    path = candidate
                    break

        if path and Path(path).exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            config = cls.model_validate(data)
        else:
            config = cls()

        config._load_env_overrides()
        return config

    def _load_env_overrides(self) -> None:
        env_mappings = {
            "DEEPFORGE_API_KEY": "default_model.api_key",
            "DEEPFORGE_MODEL": "default_model.model",
            "DEEPFORGE_BASE_URL": "default_model.base_url",
            "DEEPSEEK_API_KEY": "default_model.api_key",
            "QWEN_API_KEY": "default_model.api_key",
            "GLM_API_KEY": "default_model.api_key",
            "KIMI_API_KEY": "default_model.api_key",
            "DEEPFORGE_EVOLUTION": "evolution.enabled",
        }
        for env_key, config_path in env_mappings.items():
            value = os.environ.get(env_key)
            if value:
                parts = config_path.split(".")
                obj: Any = self
                for part in parts[:-1]:
                    obj = getattr(obj, part)
                if config_path == "evolution.enabled":
                    setattr(obj, parts[-1], value.lower() not in ("false", "0", "no", "off"))
                else:
                    setattr(obj, parts[-1], value)

    @staticmethod
    def _load_dotenv():
        """从 .env 文件加载环境变量"""
        env_candidates = [Path.cwd() / ".env", Path.home() / ".deepforge" / ".env"]
        for env_path in env_candidates:
            if env_path.exists():
                for line in env_path.read_text().strip().split("\n"):
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if key and value and key not in os.environ:
                        os.environ[key] = value
                break

    def get_model_config(self, agent_name: str) -> ModelConfig:
        agent_cfg = self.agents.get(agent_name)
        if agent_cfg and agent_cfg.model and agent_cfg.model in self.models:
            return self.models[agent_cfg.model]
        return self.default_model

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, allow_unicode=True)
