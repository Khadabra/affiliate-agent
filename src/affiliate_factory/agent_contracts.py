"""Typed contracts for the local-first modular agent foundation.

These contracts describe agent execution only.  They deliberately remain
separate from the affiliate content workflow models in ``models.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskStatus(StrEnum):
    """States through which an agent task may move."""

    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.IDLE: {TaskStatus.QUEUED},
    TaskStatus.QUEUED: {TaskStatus.RUNNING},
    TaskStatus.RUNNING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
}


class AgentError(BaseModel):
    """Safe, structured execution error information."""

    model_config = ConfigDict(extra="forbid")

    error_type: str
    message: str

    @field_validator("error_type", "message")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Agent error fields must not be empty")
        return value.strip()


class AgentMetadata(BaseModel):
    """Public metadata used by the registry and future dashboard."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str
    version: str
    description: str
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("agent_id", "name", "version", "description")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Agent metadata text fields must not be empty")
        return value.strip()

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Agent capabilities must not contain empty values")
        return cleaned


class AgentTask(BaseModel):
    """Validated input and lifecycle state for one agent execution."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    task_id: str
    agent_id: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str
    parent_task_id: str | None = None
    status: TaskStatus = TaskStatus.IDLE
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "status" and "status" in self.__dict__:
            current = TaskStatus(self.__dict__["status"])
            target = TaskStatus(value)
            if target != current and target not in ALLOWED_TASK_TRANSITIONS[current]:
                raise ValueError(f"Invalid task transition: {current.value} -> {target.value}")
        super().__setattr__(name, value)

    @field_validator("task_id", "agent_id", "correlation_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Task identifiers must not be empty")
        return value.strip()

    @field_validator("created_at", "started_at", "completed_at")
    @classmethod
    def normalize_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def transition_to(self, target: TaskStatus) -> None:
        """Apply one valid lifecycle transition or raise ``ValueError``."""

        target = TaskStatus(target)
        if target not in ALLOWED_TASK_TRANSITIONS[self.status]:
            raise ValueError(f"Invalid task transition: {self.status.value} -> {target.value}")
        self.status = target
        now = datetime.now(timezone.utc)
        if target is TaskStatus.RUNNING:
            self.started_at = now
        elif target in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            self.completed_at = now


class AgentResult(BaseModel):
    """Structured terminal result returned by the agent orchestrator."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    status: TaskStatus
    output_data: dict[str, Any] = Field(default_factory=dict)
    error: AgentError | None = None
    started_at: datetime
    completed_at: datetime
    execution_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("task_id", "agent_id")
    @classmethod
    def validate_result_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Result identifiers must not be empty")
        return value.strip()

    @field_validator("status")
    @classmethod
    def validate_terminal_status(cls, value: TaskStatus) -> TaskStatus:
        if value not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            raise ValueError("Agent results must have a terminal status")
        return value

    @field_validator("started_at", "completed_at")
    @classmethod
    def normalize_result_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_error_matches_status(self) -> "AgentResult":
        if self.status is TaskStatus.FAILED and self.error is None:
            raise ValueError("Failed agent results must preserve structured error information")
        if self.status is TaskStatus.COMPLETED and self.error is not None:
            raise ValueError("Completed agent results must not contain an error")
        return self


class AgentEvent(BaseModel):
    """Observable action emitted during one agent task lifecycle."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    task_id: str
    agent_id: str
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str

    @field_validator("event_id", "task_id", "agent_id", "event_type", "correlation_id")
    @classmethod
    def validate_event_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Agent event identifiers and type must not be empty")
        return value.strip()

    @field_validator("timestamp")
    @classmethod
    def normalize_event_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
