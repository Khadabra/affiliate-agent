"""Integration coverage for Phase 3.2 workflow coordination."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from affiliate_factory.agent import BaseAgent
from affiliate_factory.agent_context import ExecutionContext
from affiliate_factory.agent_orchestrator import AgentOrchestrator
from affiliate_factory.agent_registry import AgentRegistry
from affiliate_factory.db import Database
from affiliate_factory.workflow_contracts import (
    ApprovalDecision,
    WorkflowDefinition,
    WorkflowExecutionRequest,
    WorkflowStep,
    WorkflowStatus,
    WorkflowStepStatus,
)
from affiliate_factory.workflow_events import InMemoryWorkflowEventSink
from affiliate_factory.workflow_executor import (
    DuplicateWorkflowExecutionError,
    InvalidWorkflowResumeError,
    WorkflowExecutor,
    WorkflowPersistenceError,
)


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


class TextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    length: int


class UppercaseAgent(BaseAgent[TextInput, TextOutput]):
    input_model = TextInput
    output_model = TextOutput
    metadata = {
        "agent_id": "workflow.upper",
        "name": "Workflow Uppercase",
        "version": "1.0.0",
        "description": "Test-only deterministic uppercase agent.",
        "capabilities": ["uppercase"],
    }

    def __init__(self) -> None:
        from affiliate_factory.agent_contracts import AgentMetadata

        self.metadata = AgentMetadata.model_validate(self.metadata)

    def execute(self, input_data: TextInput, context: ExecutionContext) -> TextOutput:
        return TextOutput(text=input_data.text.upper(), length=len(input_data.text))


class SuffixAgent(BaseAgent[TextInput, TextOutput]):
    input_model = TextInput
    output_model = TextOutput
    metadata = {
        "agent_id": "workflow.suffix",
        "name": "Workflow Suffix",
        "version": "1.0.0",
        "description": "Test-only deterministic suffix agent.",
        "capabilities": ["suffix"],
    }

    def __init__(self) -> None:
        from affiliate_factory.agent_contracts import AgentMetadata

        self.metadata = AgentMetadata.model_validate(self.metadata)

    def execute(self, input_data: TextInput, context: ExecutionContext) -> TextOutput:
        return TextOutput(text=f"{input_data.text}!", length=len(input_data.text) + 1)


class TransientAgent(BaseAgent[TextInput, TextOutput]):
    input_model = TextInput
    output_model = TextOutput
    metadata = {
        "agent_id": "workflow.transient",
        "name": "Workflow Transient",
        "version": "1.0.0",
        "description": "Test-only transient failure agent.",
        "capabilities": ["transient"],
    }

    def __init__(self) -> None:
        from affiliate_factory.agent_contracts import AgentMetadata

        self.metadata = AgentMetadata.model_validate(self.metadata)
        self.calls = 0

    def execute(self, input_data: TextInput, context: ExecutionContext) -> TextOutput:
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("temporary provider timeout")
        return TextOutput(text=input_data.text, length=len(input_data.text))


class PermanentAgent(BaseAgent[TextInput, TextOutput]):
    input_model = TextInput
    output_model = TextOutput
    metadata = {
        "agent_id": "workflow.permanent",
        "name": "Workflow Permanent",
        "version": "1.0.0",
        "description": "Test-only permanent failure agent.",
        "capabilities": ["permanent"],
    }

    def __init__(self) -> None:
        from affiliate_factory.agent_contracts import AgentMetadata

        self.metadata = AgentMetadata.model_validate(self.metadata)
        self.calls = 0

    def execute(self, input_data: TextInput, context: ExecutionContext) -> TextOutput:
        self.calls += 1
        raise ValueError("permanent failure")


class FailingPersistenceDatabase(Database):
    def __init__(self, db_path: Path) -> None:
        self.fail_next_workflow_update = True
        super().__init__(db_path)

    def update_workflow_execution(self, record, steps, event=None) -> None:
        if self.fail_next_workflow_update:
            self.fail_next_workflow_update = False
            raise OSError("simulated persistence interruption")
        super().update_workflow_execution(record, steps, event)


class FailOnceWorkflowEventSink(InMemoryWorkflowEventSink):
    def __init__(self, event_type: str) -> None:
        super().__init__()
        self.event_type_to_fail = event_type
        self.failed = False

    def publish(self, event) -> None:
        if event.event_type == self.event_type_to_fail and not self.failed:
            self.failed = True
            raise OSError("simulated in-memory observer failure")
        super().publish(event)


class TestPhase32Workflow(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "workflow.db")
        registry = AgentRegistry()
        for agent in (UppercaseAgent(), SuffixAgent(), TransientAgent(), PermanentAgent()):
            registry.register(agent)
        self.agent_orchestrator = AgentOrchestrator(
            registry,
            ExecutionContext(db=self.db, execution_metadata={"phase": "3.2-test"}),
        )
        self.events = InMemoryWorkflowEventSink()
        self.executor = WorkflowExecutor(self.agent_orchestrator, self.events)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def request(self, execution_id: str, workflow_id: str = "workflow.test") -> WorkflowExecutionRequest:
        return WorkflowExecutionRequest(
            execution_id=execution_id,
            workflow_id=workflow_id,
            input_data={"text": "hello"},
            correlation_id=f"corr-{execution_id}",
        )

    def test_workflow_definition_rejects_invalid_graph_and_accepts_capability_selector(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="valid",
            name="Valid",
            description="Valid workflow",
            version="1.0",
            steps=[
                WorkflowStep(step_id="a", required_capability="uppercase"),
                WorkflowStep(step_id="b", agent_id="workflow.suffix", dependencies=["a"]),
            ],
        )
        self.assertEqual(definition.steps[0].required_capability, "uppercase")
        with self.assertRaises(ValueError):
            WorkflowDefinition(
                workflow_id="cycle",
                name="Cycle",
                description="Invalid",
                version="1.0",
                steps=[
                    WorkflowStep(step_id="a", agent_id="workflow.upper", dependencies=["b"]),
                    WorkflowStep(step_id="b", agent_id="workflow.suffix", dependencies=["a"]),
                ],
            )

    def test_successful_sequential_workflow_maps_outputs_and_persists_events(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="workflow.test",
            name="Sequential",
            description="Two dependent steps",
            version="1.0",
            steps=[
                WorkflowStep(
                    step_id="upper",
                    agent_id="workflow.upper",
                    input_mapping={"text": "input.text"},
                    output_mapping={"output.text": "final.text"},
                ),
                WorkflowStep(
                    step_id="suffix",
                    agent_id="workflow.suffix",
                    dependencies=["upper"],
                    input_mapping={"text": "steps.upper.output.text"},
                ),
            ],
        )
        result = self.executor.execute(definition, self.request("success"))
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertEqual(result.step_results[0].status, WorkflowStepStatus.COMPLETED)
        self.assertEqual(result.step_results[1].output_data["text"], "HELLO!")
        self.assertEqual(result.output_data["final"]["text"], "HELLO")
        self.assertEqual(
            [event.event_type for event in self.events.events],
            [
                "workflow_created",
                "workflow_started",
                "step_started",
                "step_completed",
                "step_started",
                "step_completed",
                "workflow_completed",
            ],
        )
        self.assertTrue(all(event.correlation_id == "corr-success" for event in self.events.events))
        self.assertEqual(len(self.db.list_workflow_events("success")), 0)
        self.assertEqual(len(self.db.list_agent_events()), 8)

    def test_default_database_sink_persists_workflow_events(self) -> None:
        registry = AgentRegistry()
        registry.register(UppercaseAgent())
        durable_executor = WorkflowExecutor(
            AgentOrchestrator(registry, ExecutionContext(db=self.db))
        )
        definition = WorkflowDefinition(
            workflow_id="workflow.durable",
            name="Durable events",
            description="Uses SQLite workflow event sink",
            version="1.0",
            steps=[
                WorkflowStep(
                    step_id="one",
                    agent_id="workflow.upper",
                    input_mapping={"text": "input.text"},
                )
            ],
        )
        result = durable_executor.execute(
            definition,
            WorkflowExecutionRequest(
                execution_id="durable-events",
                workflow_id="workflow.durable",
                input_data={"text": "stored"},
                correlation_id="corr-durable",
            ),
        )
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertEqual(len(self.db.list_workflow_events("durable-events")), 5)
        self.assertTrue(
            all(event.correlation_id == "corr-durable" for event in self.db.list_workflow_events("durable-events"))
        )

    def test_unknown_agent_and_failed_step_block_downstream(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="workflow.test",
            name="Failure",
            description="Failure workflow",
            version="1.0",
            steps=[
                WorkflowStep(
                    step_id="bad",
                    agent_id="workflow.permanent",
                    retry_limit=2,
                    input_mapping={"text": "input.text"},
                ),
                WorkflowStep(step_id="downstream", agent_id="workflow.suffix", dependencies=["bad"]),
            ],
        )
        result = self.executor.execute(definition, self.request("failure"))
        self.assertEqual(result.status, WorkflowStatus.FAILED)
        self.assertEqual(result.step_results[0].attempts, 1)
        self.assertEqual(result.step_results[1].status, WorkflowStepStatus.IDLE)
        self.assertEqual(PermanentAgent().calls, 0)
        unknown_result = self.executor.execute(
            WorkflowDefinition(
                workflow_id="workflow.test",
                name="Unknown",
                description="Unknown agent",
                version="1.0",
                steps=[WorkflowStep(step_id="missing", agent_id="missing.agent")],
            ),
            self.request("unknown"),
        )
        self.assertEqual(unknown_result.status, WorkflowStatus.FAILED)
        self.assertEqual(unknown_result.step_results[0].status, WorkflowStepStatus.FAILED)

    def test_transient_failure_retries_and_validation_failure_does_not_retry(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="workflow.test",
            name="Retry",
            description="Retry workflow",
            version="1.0",
            steps=[
                WorkflowStep(
                    step_id="retry",
                    agent_id="workflow.transient",
                    retry_limit=1,
                    input_mapping={"text": "input.text"},
                )
            ],
        )
        result = self.executor.execute(definition, self.request("retry"))
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertEqual(result.step_results[0].attempts, 2)
        self.assertEqual(len(self.db.list_agent_events("retry:retry:attempt-1")), 4)
        self.assertEqual(len(self.db.list_agent_events("retry:retry:attempt-2")), 4)

        invalid = WorkflowDefinition(
            workflow_id="workflow.test",
            name="No retry validation",
            description="Invalid input",
            version="1.0",
            steps=[WorkflowStep(step_id="invalid", agent_id="workflow.upper", retry_limit=3)],
        )
        invalid_request = WorkflowExecutionRequest(
            execution_id="invalid-input",
            workflow_id="workflow.test",
            input_data={},
            correlation_id="corr-invalid-input",
        )
        invalid_result = self.executor.execute(invalid, invalid_request)
        self.assertEqual(invalid_result.status, WorkflowStatus.FAILED)
        self.assertEqual(invalid_result.step_results[0].attempts, 1)

    def test_duplicate_execution_is_rejected_and_task_ids_are_isolated(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="workflow.test",
            name="Duplicate",
            description="Duplicate guard",
            version="1.0",
            steps=[WorkflowStep(step_id="one", agent_id="workflow.upper")],
        )
        self.executor.execute(definition, self.request("duplicate"))
        with self.assertRaises(DuplicateWorkflowExecutionError):
            self.executor.execute(definition, self.request("duplicate"))
        self.assertIsNotNone(self.db.get_workflow_execution("duplicate"))

    def test_human_approval_pause_resume_and_rejection(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="workflow.test",
            name="Approval",
            description="Approval pause",
            version="1.0",
            steps=[
                WorkflowStep(
                    step_id="approval",
                    agent_id="workflow.upper",
                    input_mapping={"text": "input.text"},
                    requires_approval=True,
                ),
                WorkflowStep(
                    step_id="after",
                    agent_id="workflow.suffix",
                    dependencies=["approval"],
                    input_mapping={"text": "steps.approval.output.text"},
                ),
            ],
        )
        paused = self.executor.execute(definition, self.request("paused"))
        self.assertEqual(paused.status, WorkflowStatus.PAUSED)
        self.assertEqual(paused.paused_step_id, "approval")
        self.assertEqual([event.event_type for event in self.events.events][-1], "workflow_paused")
        resumed = self.executor.resume(definition, "paused", ApprovalDecision.APPROVE)
        self.assertEqual(resumed.status, WorkflowStatus.COMPLETED)
        self.assertEqual(resumed.step_results[-1].status, WorkflowStepStatus.COMPLETED)

        rejected = self.executor.execute(definition, self.request("rejected"))
        rejected_result = self.executor.resume(definition, rejected.execution_id, ApprovalDecision.REJECT)
        self.assertEqual(rejected_result.status, WorkflowStatus.REJECTED)
        self.assertEqual(rejected_result.step_results[1].status, WorkflowStepStatus.IDLE)

    def test_persistence_failure_leaves_recoverable_state_and_recovery_reuses_execution(self) -> None:
        failing_db = FailingPersistenceDatabase(Path(self.temp_dir.name) / "recover.db")
        registry = AgentRegistry()
        registry.register(UppercaseAgent())
        agent_orchestrator = AgentOrchestrator(registry, ExecutionContext(db=failing_db))
        executor = WorkflowExecutor(agent_orchestrator)
        definition = WorkflowDefinition(
            workflow_id="workflow.recovery",
            name="Recovery",
            description="Persistence recovery",
            version="1.0",
            steps=[
                WorkflowStep(
                    step_id="one",
                    agent_id="workflow.upper",
                    input_mapping={"text": "input.text"},
                )
            ],
        )
        with self.assertRaises(WorkflowPersistenceError):
            executor.execute(
                definition,
                WorkflowExecutionRequest(
                    execution_id="recover-me",
                    workflow_id="workflow.recovery",
                    input_data={"text": "recover"},
                    correlation_id="corr-recover",
                ),
            )
        self.assertEqual(failing_db.get_workflow_execution("recover-me").status, WorkflowStatus.QUEUED)
        recovered = executor.recover(definition, "recover-me")
        self.assertEqual(recovered.status, WorkflowStatus.COMPLETED)
        self.assertEqual(len(failing_db.list_agent_events("recover-me:one:attempt-1")), 4)

    def test_in_memory_event_sink_failure_preserves_non_terminal_recovery_without_duplicate_task(self) -> None:
        failing_sink = FailOnceWorkflowEventSink("step_completed")
        executor = WorkflowExecutor(self.agent_orchestrator, failing_sink)
        definition = WorkflowDefinition(
            workflow_id="workflow.test",
            name="In-memory recovery",
            description="Observer failure recovery",
            version="1.0",
            steps=[
                WorkflowStep(
                    step_id="one",
                    agent_id="workflow.upper",
                    input_mapping={"text": "input.text"},
                )
            ],
        )
        with self.assertRaises(WorkflowPersistenceError):
            executor.execute(definition, self.request("memory-recovery"))
        self.assertEqual(
            self.db.get_workflow_execution("memory-recovery").status,
            WorkflowStatus.RUNNING,
        )
        self.assertEqual(
            self.db.list_workflow_steps("memory-recovery")[0].status,
            WorkflowStepStatus.COMPLETED,
        )

        recovered = executor.recover(definition, "memory-recovery")
        self.assertEqual(recovered.status, WorkflowStatus.COMPLETED)
        self.assertEqual(len(self.db.list_agent_events("memory-recovery:one:attempt-1")), 4)


if __name__ == "__main__":
    unittest.main()
