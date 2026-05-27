from __future__ import annotations

import enum
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, enum.Enum):
    USER_INPUT = "user_input"
    TASK = "task"
    RESULT = "result"
    FEEDBACK = "feedback"
    ERROR = "error"
    HANDOFF = "handoff"
    MEMORY = "memory"
    SYSTEM = "system"


class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: MessageType
    sender: str
    receiver: str
    content: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    parent_id: str | None = None

    def reply(self, content: str, msg_type: MessageType = MessageType.RESULT, **data: Any) -> Message:
        return Message(
            type=msg_type,
            sender=self.receiver,
            receiver=self.sender,
            content=content,
            data=data,
            parent_id=self.id,
        )


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str | None = None
    created_by: str = "system"
    subtasks: list[Task] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    completed_at: float | None = None


class WorkContext(BaseModel):
    project_name: str = ""
    user_request: str = ""
    current_phase: str = "init"
    tasks: list[Task] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    conversation_history: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_message(self, msg: Message) -> None:
        self.conversation_history.append(msg)

    def get_messages_for(self, agent_name: str) -> list[Message]:
        return [m for m in self.conversation_history if m.receiver == agent_name or m.sender == agent_name]

    def add_artifact(self, key: str, value: Any) -> None:
        self.artifacts[key] = value

    def get_task(self, task_id: str) -> Task | None:
        for t in self.tasks:
            if t.id == task_id:
                return t
            for st in t.subtasks:
                if st.id == task_id:
                    return st
        return None
