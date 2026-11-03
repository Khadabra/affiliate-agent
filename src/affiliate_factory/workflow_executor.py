"""Sequential dependency-aware executor for multi-agent workflows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from affiliate_factory.agent_orchestrator import AgentOrchestrator
from affiliate_factory.agent_registry import AgentRegistryError
from affiliate_factory.workflow_contracts import (
    ApprovalDecision,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowExecutionRecord,
    WorkflowExecutionRequest,
    WorkflowResult,
    WorkflowStep,
    WorkflowStepResult,
    WorkflowStepStatus,
    WorkflowStatus,
)
from affiliate_factory.workflow_events import DatabaseWorkflowEventSink, WorkflowEventSink


class WorkflowExecutionError(RuntimeError):
    """Base error for workflow execution control failures."""


class DuplicateWorkflowExecutionError(WorkflowExecutionError):
    """Raised when an execution ID is reused."""


class InvalidWorkflowResumeError(WorkflowExecutionError):
    """Raised when a workflow cannot be resumed in its current state."""


class WorkflowPersistenceError(WorkflowExecutionError):
    """Raised when workflow state cannot be persisted safely."""


class WorkflowExecutor:
    """Run registered agents sequentially while preserving workflow state."""

    def __init__(
        self,
        agent_orchestrator: AgentOrchestrator,
        event_sink: WorkflowEventSink | None = None,
    ) -> None:
        self.agent_orchestrator = agent_orchestrator
        self.db = agent_orchestrator.context.db
        self.registry = agent_orchestrator.registry
        self.event_sink = event_sink or DatabaseWorkflowEventSink(self.db)

    def execute(
        self,
        workflow: WorkflowDefinition | dict[str, Any],
        request: WorkflowExecutionRequest | dict[str, Any],
    ) -> WorkflowResult:
        """Create and execute one new workflow execution."""
        definition = WorkflowDefinition.model_validate(workflow)
        execution_request = WorkflowExecutionRequest.model_validate(request)
        if execution_request.workflow_id != definition.workflow_id:
            raise ValueError("Workflow request ID does not match workflow definition")
        if self.db.get_workflow_execution(execution_request.execution_id) is not None:
            raise DuplicateWorkflowExecutionError(
                f"Workflow execution '{execution_request.execution_id}' already exists"
            )

        now = datetime.now(timezone.utc)
        record = WorkflowExecutionRecord(
            execution_id=execution_request.execution_id,
            workflow_id=definition.workflow_id,
            workflow_version=definition.version,
            status=WorkflowStatus.QUEUED,
            input_data=execution_request.input_data,
            correlation_id=execution_request.correlation_id,
            parent_execution_id=execution_request.parent_execution_id,
            created_at=now,
            updated_at=now,
        )
        steps = [WorkflowStepResult(step_id=step.step_id, status=WorkflowStepStatus.IDLE) for step in definition.steps]
        self._create_record(execution_request, definition, record, steps)
        record = self._update_record(
            record.model_copy(update={"status": WorkflowStatus.RUNNING, "updated_at": self._now()}),
            steps,
            self._event(record, "workflow_started", payload={"status": WorkflowStatus.RUNNING.value}),
        )
        return self._run(definition, record, steps)

    def resume(
        self,
        workflow: WorkflowDefinition | dict[str, Any],
        execution_id: str,
        decision: ApprovalDecision | str,
        approval_data: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Resume a paused approval gate only after an explicit decision."""
        definition = WorkflowDefinition.model_validate(workflow)
        record = self.db.get_workflow_execution(execution_id)
        if record is None:
            raise InvalidWorkflowResumeError(f"Unknown workflow execution: '{execution_id}'")
        self._validate_resume_definition(record, definition)
        if record.status is not WorkflowStatus.PAUSED:
            raise InvalidWorkflowResumeError(
                f"Workflow execution '{execution_id}' is not paused (status={record.status.value})"
            )
        steps = self.db.list_workflow_steps(execution_id)
        decision = ApprovalDecision(decision)
        approval_data = dict(approval_data or {})
        if decision is ApprovalDecision.REJECT:
            rejected = record.model_copy(
                update={
                    "status": WorkflowStatus.REJECTED,
                    "error_type": "HumanRejected",
                    "error_message": "Human approval decision rejected the workflow",
                    "updated_at": self._now(),
                }
            )
            self._update_record(
                rejected,
                steps,
                self._event(
                    rejected,
                    "workflow_failed",
                    payload={"status": WorkflowStatus.REJECTED.value, "decision": decision.value},
                ),
            )
            return self._result(rejected, steps)

        resumed = record.model_copy(
            update={
                "status": WorkflowStatus.RUNNING,
                "updated_at": self._now(),
                "error_type": None,
                "error_message": None,
                "output_data": {
                    **record.output_data,
                    "approval_decision": decision.value,
                    **approval_data,
                },
            }
        )
        self._update_record(
            resumed,
            steps,
            self._event(resumed, "workflow_resumed", payload={"decision": decision.value}),
        )
        return self._run(definition, resumed, steps)

    def recover(self, workflow: WorkflowDefinition | dict[str, Any], execution_id: str) -> WorkflowResult:
        """Continue a non-terminal execution after a recoverable persistence interruption."""
        definition = WorkflowDefinition.model_validate(workflow)
        record = self.db.get_workflow_execution(execution_id)
        if record is None:
            raise InvalidWorkflowResumeError(f"Unknown workflow execution: '{execution_id}'")
        self._validate_resume_definition(record, definition)
        if record.status not in {WorkflowStatus.QUEUED, WorkflowStatus.RUNNING}:
            raise InvalidWorkflowResumeError(
                f"Workflow execution '{execution_id}' is not recoverable (status={record.status.value})"
            )
        steps = self.db.list_workflow_steps(execution_id)
        running = record.model_copy(update={"status": WorkflowStatus.RUNNING, "updated_at": self._now()})
        self._update_record(
            running,
            steps,
            self._event(running, "workflow_resumed", payload={"recovery": True}),
        )
        return self._run(definition, running, steps)

    def _run(
        self,
        definition: WorkflowDefinition,
        record: WorkflowExecutionRecord,
        steps: list[WorkflowStepResult],
    ) -> WorkflowResult:
        results = {step.step_id: step for step in steps}
        outputs = {
            step.step_id: step.output_data
            for step in steps
            if step.status is WorkflowStepStatus.COMPLETED
        }
        workflow_outputs = dict(record.output_data)
        remaining = [step for step in definition.steps if results[step.step_id].status is not WorkflowStepStatus.COMPLETED]

        while remaining:
            ready = next(
                (
                    step
                    for step in remaining
                    if all(results[dependency].status is WorkflowStepStatus.COMPLETED for dependency in step.dependencies)
                ),
                None,
            )
            if ready is None:
                return self._fail_workflow(
                    record,
                    results,
                    "WorkflowDependencyError",
                    "No remaining workflow step has all dependencies completed",
                )

            step_result = results[ready.step_id]
            record = record.model_copy(
                update={"current_step_id": ready.step_id, "updated_at": self._now()}
            )
            try:
                agent = self._resolve_agent(ready)
                step_result = step_result.model_copy(
                    update={"status": WorkflowStepStatus.RUNNING, "attempts": step_result.attempts}
                )
                results[ready.step_id] = step_result
                self._update_record(
                    record,
                    list(results.values()),
                    self._event(
                        record,
                        "step_started",
                        step_id=ready.step_id,
                        payload={"status": WorkflowStepStatus.RUNNING.value},
                    ),
                )
                workflow_context = {**record.input_data, **record.output_data}
                input_data = self._build_input(ready, workflow_context, outputs)
                succeeded, step_result = self._execute_step(
                    record, ready, agent.metadata.agent_id, input_data, step_result
                )
                results[ready.step_id] = step_result
                if not succeeded:
                    return self._fail_step(
                        record,
                        results,
                        ready,
                        RuntimeError(step_result.error_message or "Workflow step failed"),
                        error_type=step_result.error_type,
                    )
                outputs[ready.step_id] = step_result.output_data
                self._apply_output_mapping(ready, step_result.output_data, workflow_outputs)
                record = record.model_copy(update={"output_data": workflow_outputs, "updated_at": self._now()})
                self._update_record(
                    record,
                    list(results.values()),
                    self._event(
                        record,
                        "step_completed",
                        step_id=ready.step_id,
                        task_id=step_result.task_id,
                        payload={"attempts": step_result.attempts},
                    ),
                )
                remaining.remove(ready)
                if ready.requires_approval:
                    paused = record.model_copy(
                        update={"status": WorkflowStatus.PAUSED, "updated_at": self._now()}
                    )
                    step_result = step_result.model_copy(update={"status": WorkflowStepStatus.COMPLETED})
                    results[ready.step_id] = step_result
                    self._update_record(
                        paused,
                        list(results.values()),
                        self._event(
                            paused,
                            "workflow_paused",
                            step_id=ready.step_id,
                            task_id=step_result.task_id,
                            payload={"reason": "human_approval_required"},
                        ),
                    )
                    return self._result(paused, list(results.values()), paused_step_id=ready.step_id)
            except WorkflowPersistenceError:
                # The SQLite state may already be committed while an injected
                # in-memory observer failed. Leave the non-terminal state
                # recoverable instead of misclassifying it as agent failure.
                raise
            except Exception as exc:
                return self._fail_step(record, results, ready, exc)

        completed = record.model_copy(
            update={"status": WorkflowStatus.COMPLETED, "current_step_id": None, "updated_at": self._now()}
        )
        self._update_record(
            completed,
            list(results.values()),
            self._event(completed, "workflow_completed", payload={"status": completed.status.value}),
        )
        return self._result(completed, list(results.values()))

    def _execute_step(
        self,
        record: WorkflowExecutionRecord,
        step: WorkflowStep,
        agent_id: str,
        input_data: dict[str, Any],
        step_result: WorkflowStepResult,
    ) -> tuple[bool, WorkflowStepResult]:
        last_result = None
        for attempt in range(step_result.attempts + 1, step_result.attempts + step.retry_limit + 2):
            task_id = f"{record.execution_id}:{step.step_id}:attempt-{attempt}"
            persisted = self.db.get_agent_result(task_id)
            if persisted is None:
                task = {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "input_data": input_data,
                    "context": {
                        "workflow_execution_id": record.execution_id,
                        "workflow_step_id": step.step_id,
                    },
                    "correlation_id": record.correlation_id,
                }
                persisted = self.agent_orchestrator.execute(task)
            last_result = persisted
            current = step_result.model_copy(
                update={
                    "task_id": task_id,
                    "attempts": attempt,
                    "status": WorkflowStepStatus.COMPLETED
                    if persisted.status.value == "completed"
                    else WorkflowStepStatus.FAILED,
                    "output_data": persisted.output_data,
                    "error_type": persisted.error.error_type if persisted.error else None,
                    "error_message": persisted.error.message if persisted.error else None,
                }
            )
            if persisted.status.value == "completed":
                return True, current
            if not persisted.error or persisted.error.error_type not in step.retryable_errors:
                return False, current
        return False, current

    def _fail_step(
        self,
        record: WorkflowExecutionRecord,
        results: dict[str, WorkflowStepResult],
        step: WorkflowStep,
        error: Exception,
        error_type: str | None = None,
    ) -> WorkflowResult:
        current = results[step.step_id].model_copy(
            update={
                "status": WorkflowStepStatus.FAILED,
                "error_type": error_type or type(error).__name__,
                "error_message": str(error) or "Workflow step failed",
            }
        )
        results[step.step_id] = current
        failed = record.model_copy(
            update={
                "status": WorkflowStatus.FAILED,
                "error_type": current.error_type,
                "error_message": current.error_message,
                "updated_at": self._now(),
            }
        )
        self._update_record(
            failed,
            list(results.values()),
            self._event(
                failed,
                "step_failed",
                step_id=step.step_id,
                task_id=current.task_id,
                payload={"error_type": current.error_type},
            ),
        )
        self._update_record(
            failed,
            list(results.values()),
            self._event(failed, "workflow_failed", payload={"error_type": current.error_type}),
        )
        return self._result(failed, list(results.values()))

    def _fail_workflow(
        self,
        record: WorkflowExecutionRecord,
        results: dict[str, WorkflowStepResult],
        error_type: str,
        message: str,
    ) -> WorkflowResult:
        failed = record.model_copy(
            update={
                "status": WorkflowStatus.FAILED,
                "error_type": error_type,
                "error_message": message,
                "updated_at": self._now(),
            }
        )
        self._update_record(
            failed,
            list(results.values()),
            self._event(failed, "workflow_failed", payload={"error_type": error_type}),
        )
        return self._result(failed, list(results.values()))

    def _resolve_agent(self, step: WorkflowStep):
        if step.agent_id:
            return self.registry.get(step.agent_id)
        if step.required_capability:
            return self.registry.get_by_capability(step.required_capability)
        raise AgentRegistryError(f"Step '{step.step_id}' has no agent selector")

    @staticmethod
    def _build_input(
        step: WorkflowStep,
        workflow_input: dict[str, Any],
        outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        data = dict(step.input_data)
        for target, source in step.input_mapping.items():
            data[target] = WorkflowExecutor._resolve_path(source, workflow_input, outputs)
        return data

    @staticmethod
    def _resolve_path(path: str, workflow_input: dict[str, Any], outputs: dict[str, dict[str, Any]]) -> Any:
        parts = path.split(".")
        if len(parts) >= 2 and parts[0] in {"input", "workflow"}:
            value: Any = workflow_input
            parts = parts[1:]
        elif len(parts) >= 3 and parts[0] == "steps" and parts[2] == "output":
            value = outputs[parts[1]]
            parts = parts[3:]
        else:
            raise ValueError(f"Unsupported workflow mapping path: '{path}'")
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                raise KeyError(f"Workflow mapping path not found: '{path}'")
            value = value[part]
        return value

    @staticmethod
    def _apply_output_mapping(step: WorkflowStep, output: dict[str, Any], workflow_outputs: dict[str, Any]) -> None:
        for source, target in step.output_mapping.items():
            value = WorkflowExecutor._resolve_output_path(source, output)
            WorkflowExecutor._set_path(workflow_outputs, target, value)

    @staticmethod
    def _resolve_output_path(path: str, output: dict[str, Any]) -> Any:
        parts = path.split(".")
        value: Any = output
        if parts and parts[0] == "output":
            parts = parts[1:]
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                raise KeyError(f"Workflow output mapping path not found: '{path}'")
            value = value[part]
        return value

    @staticmethod
    def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        if not parts or any(not part for part in parts):
            raise ValueError(f"Invalid workflow output target: '{path}'")
        current = target
        for part in parts[:-1]:
            child = current.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError(f"Workflow output target conflicts with scalar: '{path}'")
            current = child
        current[parts[-1]] = value

    def _create_record(self, request, definition, record, steps) -> None:
        event = self._event(record, "workflow_created", payload={"status": record.status.value})
        try:
            if isinstance(self.event_sink, DatabaseWorkflowEventSink):
                self.db.save_workflow_execution(request, definition, record, steps, event=event)
            else:
                self.db.save_workflow_execution(request, definition, record, steps)
                self.event_sink.publish(event)
        except Exception as exc:
            raise WorkflowPersistenceError(f"Could not create workflow execution: {exc}") from exc

    def _update_record(self, record, steps, event):
        try:
            if isinstance(self.event_sink, DatabaseWorkflowEventSink):
                self.db.update_workflow_execution(record, steps, event=event)
            else:
                self.db.update_workflow_execution(record, steps)
                self.event_sink.publish(event)
        except Exception as exc:
            raise WorkflowPersistenceError(f"Could not persist workflow state: {exc}") from exc
        return record

    def _event(self, record, event_type, *, step_id=None, task_id=None, payload=None):
        return WorkflowEvent(
            event_id=str(uuid.uuid4()),
            execution_id=record.execution_id,
            workflow_id=record.workflow_id,
            step_id=step_id,
            task_id=task_id,
            event_type=event_type,
            payload=payload or {},
            correlation_id=record.correlation_id,
        )

    def _validate_resume_definition(self, record, definition):
        if record.workflow_id != definition.workflow_id or record.workflow_version != definition.version:
            raise InvalidWorkflowResumeError("Workflow definition does not match persisted execution")

    def _result(self, record, steps, paused_step_id=None):
        return WorkflowResult(
            execution_id=record.execution_id,
            workflow_id=record.workflow_id,
            status=record.status,
            correlation_id=record.correlation_id,
            step_results=steps,
            output_data=record.output_data,
            error_type=record.error_type,
            error_message=record.error_message,
            paused_step_id=paused_step_id or record.current_step_id if record.status is WorkflowStatus.PAUSED else None,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
