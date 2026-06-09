from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx
from openai import AsyncOpenAI

log = logging.getLogger("deepforge.model")


class ModelClient:
    def __init__(self, api_key: str, base_url: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)

    async def _chat_raw(
        self,
        messages: list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
        _is_escalation: bool = False,
    ) -> tuple[str, str]:
        """Returns (content, reasoning). Extracts <think> blocks and model_extra reasoning."""
        extra = {}
        if "397" in model or "qwen" in model.lower():
            extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": enable_thinking}}

        msg_summary = messages[-1].get("content", "")[:80] if messages else ""
        log.info("model_call | model=%s, max_tokens=%d, msgs=%d, last_msg=%s",
                 model, max_tokens, len(messages), msg_summary)

        for attempt in range(3):
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra,
                )
                break
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

        # Slot reservation: if output was truncated and we haven't escalated yet, retry with 4x tokens
        finish_reason = getattr(response.choices[0], "finish_reason", None)
        log.info("model_resp | finish=%s, content_len=%d",
                 finish_reason, len(response.choices[0].message.content or ""))
        if finish_reason == "length" and not _is_escalation:
            escalated = min(max_tokens * 4, 32768)
            log.info("max_tokens escalation: %d -> %d (finish_reason=length)", max_tokens, escalated)
            return await self._chat_raw(
                messages, model, temperature, escalated, enable_thinking, _is_escalation=True
            )

        msg = response.choices[0].message
        content = msg.content or ""
        reasoning = ""

        if hasattr(msg, "model_extra") and msg.model_extra:
            reasoning = msg.model_extra.get("reasoning", "") or ""

        if "<think>" in content and "</think>" in content:
            import re
            think_match = re.search(r"<think>([\s\S]*?)</think>", content)
            if think_match:
                think_text = think_match.group(1).strip()
                if think_text:
                    reasoning = think_text if not reasoning else reasoning + "\n" + think_text
            content = content.split("</think>", 1)[-1].strip()
        elif "</think>" in content:
            content = content.split("</think>", 1)[-1].strip()

        if not content and reasoning:
            content = reasoning

        return content, reasoning

    async def chat(
        self,
        messages: list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
    ) -> str:
        content, _ = await self._chat_raw(
            messages, model, temperature, max_tokens, enable_thinking
        )
        return content

    async def chat_with_reasoning(
        self,
        messages: list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
    ) -> tuple[str, str]:
        """Like chat(), but also returns the model's reasoning/thinking content."""
        return await self._chat_raw(
            messages, model, temperature, max_tokens, enable_thinking
        )

    async def chat_stream(
        self,
        messages: list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        extra = {}
        if "397" in model or "qwen" in model.lower():
            extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": enable_thinking}}
        for attempt in range(3):
            try:
                stream = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                    **extra,
                )
                break
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
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
