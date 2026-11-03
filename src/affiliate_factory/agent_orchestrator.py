"""Sequential execution orchestrator for the modular agent foundation.

This module intentionally does not replace ``orchestrator.py``.  The existing
module owns the affiliate content workflow; this one owns generic task
execution and lifecycle observability.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from affiliate_factory.agent_context import ExecutionContext
from affiliate_factory.agent_contracts import AgentError, AgentEvent, AgentResult, AgentTask, TaskStatus
from affiliate_factory.agent_events import DatabaseAgentEventSink
from affiliate_factory.agent_registry import AgentRegistry


class AgentOrchestrator:
    """Execute one registered agent at a time with durable lifecycle state."""

    def __init__(self, registry: AgentRegistry, context: ExecutionContext) -> None:
        self.registry = registry
        self.context = context

    def execute(self, task: AgentTask | dict[str, Any]) -> AgentResult:
        """Validate, run, persist, and return one task's terminal result."""
        validated_task = AgentTask.model_validate(task)
        agent = self.registry.get(validated_task.agent_id)
        if validated_task.status is not TaskStatus.IDLE:
            raise ValueError(
                f"Agent task '{validated_task.task_id}' must start in idle status, "
                f"got '{validated_task.status.value}'"
            )

        self._record_event(
            validated_task,
            "task_created",
            {"status": validated_task.status.value},
            create=True,
        )

        validated_task.transition_to(TaskStatus.QUEUED)
        self._record_event(validated_task, "task_queued", {"status": validated_task.status.value})

        validated_task.transition_to(TaskStatus.RUNNING)
        self._record_event(
            validated_task,
            "agent_started",
            {"agent_version": agent.metadata.version, "status": validated_task.status.value},
        )
        started_at = validated_task.started_at or datetime.now(timezone.utc)
        task_context = self.context.for_task(validated_task.context)

        try:
            validated_input = agent.validate_input(validated_task)
            output_model = agent.validate_output(agent.execute(validated_input, task_context))
            validated_task.transition_to(TaskStatus.COMPLETED)
            result = AgentResult(
                task_id=validated_task.task_id,
                agent_id=validated_task.agent_id,
                status=TaskStatus.COMPLETED,
                output_data=output_model.model_dump(mode="json"),
                started_at=started_at,
                completed_at=validated_task.completed_at or datetime.now(timezone.utc),
                execution_metadata={
                    **self.context.execution_metadata,
                    "agent_version": agent.metadata.version,
                },
            )
            self._record_event(
                validated_task,
                "agent_completed",
                {"status": validated_task.status.value},
                result=result,
            )
            return result
        except Exception as exc:
            validated_task.transition_to(TaskStatus.FAILED)
            error = AgentError(error_type=type(exc).__name__, message=str(exc) or "Agent execution failed")
            result = AgentResult(
                task_id=validated_task.task_id,
                agent_id=validated_task.agent_id,
                status=TaskStatus.FAILED,
                error=error,
                started_at=started_at,
                completed_at=validated_task.completed_at or datetime.now(timezone.utc),
                execution_metadata={
                    **self.context.execution_metadata,
                    "agent_version": agent.metadata.version,
                },
            )
            self._record_event(
                validated_task,
                "agent_failed",
                {"status": validated_task.status.value, "error_type": error.error_type},
                result=result,
            )
            return result

    def _record_event(
        self,
        task: AgentTask,
        event_type: str,
        payload: dict[str, Any],
        *,
        create: bool = False,
        result: AgentResult | None = None,
    ) -> None:
        event = AgentEvent(
            event_id=str(uuid.uuid4()),
            task_id=task.task_id,
            agent_id=task.agent_id,
            event_type=event_type,
            payload=payload,
            correlation_id=task.correlation_id,
        )
        if self.context.event_sink is None:  # defensive; ExecutionContext installs the default
            raise RuntimeError("Execution context has no event sink")
        if isinstance(self.context.event_sink, DatabaseAgentEventSink):
            if create:
                self.context.db.save_agent_task_with_event(task, event)
            else:
                self.context.db.update_agent_task_with_event(task, result, event)
            return

        if create:
            self.context.db.save_agent_task(task)
        else:
            self.context.db.update_agent_task(task, result)
        self.context.event_sink.publish(event)
