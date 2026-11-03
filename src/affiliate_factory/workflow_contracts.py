"""Pydantic contracts for sequential multi-agent workflow execution."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkflowStatus(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


ALLOWED_WORKFLOW_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.IDLE: {WorkflowStatus.QUEUED},
    WorkflowStatus.QUEUED: {WorkflowStatus.RUNNING, WorkflowStatus.FAILED},
    WorkflowStatus.RUNNING: {
        WorkflowStatus.PAUSED,
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
    },
    WorkflowStatus.PAUSED: {WorkflowStatus.RUNNING, WorkflowStatus.REJECTED},
    WorkflowStatus.COMPLETED: set(),
    WorkflowStatus.FAILED: set(),
    WorkflowStatus.REJECTED: set(),
}


class WorkflowStepStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class WorkflowStep(BaseModel):
    """One dependency-aware step in a workflow definition."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    agent_id: str | None = None
    required_capability: str | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    input_mapping: dict[str, str] = Field(default_factory=dict)
    output_mapping: dict[str, str] = Field(default_factory=dict)
    retry_limit: int = Field(default=0, ge=0, le=10)
    retryable_errors: set[str] = Field(default_factory=lambda: {"TimeoutError", "ProviderTimeoutError"})
    requires_approval: bool = False

    @field_validator("step_id", "agent_id", "required_capability")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Workflow step text fields must not be empty")
        return value.strip() if value is not None else None

    @field_validator("dependencies")
    @classmethod
    def validate_dependencies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Workflow step dependencies must be unique")
        if any(not item.strip() for item in value):
            raise ValueError("Workflow step dependencies must not be empty")
        return [item.strip() for item in value]

    @model_validator(mode="after")
    def validate_agent_selector(self) -> "WorkflowStep":
        if (self.agent_id is None) == (self.required_capability is None):
            raise ValueError("Each workflow step must specify exactly one agent_id or required_capability")
        return self


class WorkflowDefinition(BaseModel):
    """Validated reusable workflow definition."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    name: str
    description: str
    version: str
    steps: list[WorkflowStep] = Field(min_length=1)

    @field_validator("workflow_id", "name", "description", "version")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Workflow definition text fields must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def validate_graph(self) -> "WorkflowDefinition":
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Workflow step IDs must be unique")
        known = set(step_ids)
        for step in self.steps:
            unknown = set(step.dependencies) - known
            if unknown:
                raise ValueError(f"Step '{step.step_id}' has unknown dependencies: {sorted(unknown)}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("Workflow dependencies must not contain cycles")
            if step_id in visited:
                return
            visiting.add(step_id)
            step = next(item for item in self.steps if item.step_id == step_id)
            for dependency in step.dependencies:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return self


class WorkflowExecutionRequest(BaseModel):
    """Input for one workflow execution identity."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    workflow_id: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str
    parent_execution_id: str | None = None

    @field_validator("execution_id", "workflow_id", "correlation_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Workflow execution identifiers must not be empty")
        return value.strip()


class WorkflowStepResult(BaseModel):
    """Persisted result of one workflow step, including attempts."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    status: WorkflowStepStatus
    task_id: str | None = None
    attempts: int = Field(default=0, ge=0)
    output_data: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None


class WorkflowExecutionRecord(BaseModel):
    """Persisted execution state used for safe resume and inspection."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    workflow_id: str
    workflow_version: str
    status: WorkflowStatus
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    correlation_id: str
    parent_execution_id: str | None = None
    current_step_id: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_record_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class WorkflowResult(BaseModel):
    """Structured result returned by ``WorkflowExecutor``."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    workflow_id: str
    status: WorkflowStatus
    correlation_id: str
    step_results: list[WorkflowStepResult] = Field(default_factory=list)
    output_data: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    paused_step_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class WorkflowEvent(BaseModel):
    """Structured workflow event for future Agent Office consumers."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    execution_id: str
    workflow_id: str
    step_id: str | None = None
    task_id: str | None = None
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str

    @field_validator("event_id", "execution_id", "workflow_id", "event_type", "correlation_id")
    @classmethod
    def validate_event_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Workflow event identifiers and type must not be empty")
        return value.strip()

    @field_validator("step_id", "task_id")
    @classmethod
    def validate_optional_event_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Workflow event optional identifiers must not be empty")
        return value.strip() if value is not None else None

    @field_validator("timestamp")
    @classmethod
    def normalize_event_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
