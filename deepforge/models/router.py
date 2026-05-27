from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import httpx
from openai import AsyncOpenAI


class ModelClient:
    def __init__(self, api_key: str, base_url: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat(
        self,
        messages: list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        messages: list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "env_key": "QWEN_API_KEY",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "env_key": "GLM_API_KEY",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "env_key": "KIMI_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
        "env_key": "",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat",
        "env_key": "OPENROUTER_API_KEY",
    },
}


class ModelRouter:
    def __init__(self):
        self._clients: dict[str, ModelClient] = {}

    def get_client(self, api_key: str, base_url: str) -> ModelClient:
        cache_key = f"{base_url}:{api_key[:8]}"
        if cache_key not in self._clients:
            self._clients[cache_key] = ModelClient(api_key=api_key, base_url=base_url)
        return self._clients[cache_key]

    @classmethod
    def from_preset(cls, provider: str, api_key: str = "") -> ModelClient:
        preset = PROVIDER_PRESETS.get(provider)
        if not preset:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(PROVIDER_PRESETS.keys())}")

        import os
        if not api_key and preset["env_key"]:
            api_key = os.environ.get(preset["env_key"], "")

        if not api_key and provider != "ollama":
            raise ValueError(
                f"API key required for {provider}. "
                f"Set {preset['env_key']} environment variable or pass api_key."
            )

        return ModelClient(api_key=api_key or "ollama", base_url=preset["base_url"])
