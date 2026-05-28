"""
DeepForge 事件总线
Agent间通信的核心——发布/订阅模式，替代字符串传递
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    TASK_START = "task_start"
    TASK_DONE = "task_done"
    AGENT_START = "agent_start"
    AGENT_DONE = "agent_done"
    AGENT_ERROR = "agent_error"
    CODE_GENERATED = "code_generated"
    REVIEW_RESULT = "review_result"
    CONTENT_READY = "content_ready"
    CHUNK = "chunk"
    USER_MESSAGE = "user_message"


@dataclass
class Event:
    type: EventType
    sender: str
    data: dict = field(default_factory=dict)


class EventBus:
    def __init__(self):
        self._handlers: dict[EventType, list[Callable]] = {}
        self._global_handlers: list[Callable] = []

    def on(self, event_type: EventType, handler: Callable) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def on_all(self, handler: Callable) -> None:
        self._global_handlers.append(handler)

    async def emit(self, event: Event) -> None:
        tasks = []
        for h in self._global_handlers:
            tasks.append(self._call(h, event))
        for h in self._handlers.get(event.type, []):
            tasks.append(self._call(h, event))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _call(self, handler: Callable, event: Event) -> None:
        result = handler(event)
        if asyncio.iscoroutine(result):
            await result
