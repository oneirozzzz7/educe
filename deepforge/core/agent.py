from __future__ import annotations

import abc
import asyncio
from typing import Any, AsyncIterator

from deepforge.core.config import DeepForgeConfig, ModelConfig
from deepforge.core.message import Message, MessageType, WorkContext


class BaseAgent(abc.ABC):
    name: str = "base"
    role: str = "Base Agent"
    description: str = ""

    def __init__(self, config: DeepForgeConfig, model_client: Any = None):
        self.config = config
        self.model_client = model_client
        self._model_config: ModelConfig | None = None

    @property
    def model_config(self) -> ModelConfig:
        if self._model_config is None:
            self._model_config = self.config.get_model_config(self.name)
        return self._model_config

    @abc.abstractmethod
    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        yield  # type: ignore

    def build_system_prompt(self, context: WorkContext) -> str:
        return f"""你是 {self.role}。
{self.description}

## 当前项目信息
- 项目名称: {context.project_name}
- 当前阶段: {context.current_phase}
- 用户原始需求: {context.user_request}

## 工作要求
1. 输出必须结构化、清晰、可执行
2. 如果需要其他Agent协助，明确说明需要谁做什么
3. 始终围绕用户需求工作，不偏离主题"""

    async def call_model(self, messages: list[dict], context: WorkContext) -> str:
        if self.model_client is None:
            raise RuntimeError(f"Agent {self.name} has no model client configured")

        system_prompt = self.build_system_prompt(context)
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self.model_client.chat(
                    messages=full_messages,
                    model=self.model_config.model,
                    temperature=self.model_config.temperature,
                    max_tokens=self.model_config.max_tokens,
                )
                return response
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                if "401" in error_str or "403" in error_str or "authentication" in error_str:
                    raise RuntimeError(f"API认证失败 (模型: {self.model_config.model}): {e}")

                if attempt < max_retries - 1:
                    import asyncio
                    wait = (attempt + 1) * 2
                    await asyncio.sleep(wait)

        raise RuntimeError(f"模型调用失败 ({max_retries}次重试后): {last_error}")

    async def call_model_stream(self, messages: list[dict], context: WorkContext) -> AsyncIterator[str]:
        if self.model_client is None:
            raise RuntimeError(f"Agent {self.name} has no model client configured")

        system_prompt = self.build_system_prompt(context)
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        async for chunk in self.model_client.chat_stream(
            messages=full_messages,
            model=self.model_config.model,
            temperature=self.model_config.temperature,
            max_tokens=self.model_config.max_tokens,
        ):
            yield chunk

    def emit(self, receiver: str, content: str, msg_type: MessageType = MessageType.RESULT, **data: Any) -> Message:
        return Message(
            type=msg_type,
            sender=self.name,
            receiver=receiver,
            content=content,
            data=data,
        )

    def handoff(self, receiver: str, content: str, **data: Any) -> Message:
        return Message(
            type=MessageType.HANDOFF,
            sender=self.name,
            receiver=receiver,
            content=content,
            data=data,
        )
