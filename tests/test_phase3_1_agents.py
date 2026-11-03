"""Regression tests for the Phase 3.1 modular agent foundation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from affiliate_factory.agent import BaseAgent
from affiliate_factory.agent_context import ExecutionContext
from affiliate_factory.agent_contracts import AgentEvent, AgentMetadata, AgentTask, TaskStatus
from affiliate_factory.agent_orchestrator import AgentOrchestrator
from affiliate_factory.agent_provider import (
    LLMAdapterProvider,
    ProviderConfig,
    ProviderExecutionError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from affiliate_factory.agent_registry import AgentRegistry, DuplicateAgentError, UnknownAgentError
from affiliate_factory.db import Database
from affiliate_factory.llm import LLMAdapter


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    length: int


class EchoAgent(BaseAgent[EchoInput, EchoOutput]):
    input_model = EchoInput
    output_model = EchoOutput
    metadata = AgentMetadata(
        agent_id="test.echo",
        name="Test Echo Agent",
        version="1.0.0",
        description="Test-only deterministic agent.",
        capabilities=["echo", "validation"],
    )

    def execute(self, input_data: EchoInput, context: ExecutionContext) -> EchoOutput:
        context.logger.info("Executing isolated echo task")
        self.last_task_context = dict(context.task_context)
        return EchoOutput(text=input_data.text.upper(), length=len(input_data.text))


class FailingAgent(EchoAgent):
    metadata = AgentMetadata(
        agent_id="test.failing",
        name="Test Failing Agent",
        version="1.0.0",
        description="Test-only failing agent.",
        capabilities=["failure-path"],
    )

    def execute(self, input_data: EchoInput, context: ExecutionContext) -> EchoOutput:
        raise RuntimeError("intentional test failure")


class InvalidOutputAgent(EchoAgent):
    metadata = AgentMetadata(
        agent_id="test.invalid-output",
        name="Test Invalid Output Agent",
        version="1.0.0",
        description="Test-only invalid-output agent.",
        capabilities=["failure-path"],
    )

    def execute(self, input_data: EchoInput, context: ExecutionContext) -> EchoOutput:
        return {"unexpected": True}  # type: ignore[return-value]


class ErrorAdapter(LLMAdapter):
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, prompt: str) -> str:
        raise self.error


class RollbackEventDatabase(Database):
    @staticmethod
    def _insert_agent_event(conn, event) -> None:
        raise OSError("simulated agent event persistence failure")


class TestPhase31Agents(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "agent.db"
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_task(self, task_id: str, agent_id: str = "test.echo", text: str = "hello") -> AgentTask:
        return AgentTask(
            task_id=task_id,
            agent_id=agent_id,
            input_data={"text": text},
            context={"source": "unit-test"},
            correlation_id=f"correlation-{task_id}",
        )

    def make_orchestrator(self, *agents: BaseAgent) -> AgentOrchestrator:
        registry = AgentRegistry()
        for agent in agents:
            registry.register(agent)
        return AgentOrchestrator(registry, ExecutionContext(db=self.db, execution_metadata={"test": True}))

    def test_registry_registration_duplicate_and_unknown_lookup(self) -> None:
        registry = AgentRegistry()
        registry.register(EchoAgent())
        self.assertEqual(registry.get("test.echo").metadata.name, "Test Echo Agent")
        self.assertEqual([item.agent_id for item in registry.list_metadata()], ["test.echo"])
        with self.assertRaises(DuplicateAgentError):
            registry.register(EchoAgent())
        with self.assertRaises(UnknownAgentError):
            registry.get("missing.agent")

    def test_contracts_validate_inputs_outputs_and_serialization(self) -> None:
        agent = EchoAgent()
        task = self.make_task("contract-1")
        self.assertEqual(agent.validate_input(task).text, "hello")
        output = agent.validate_output({"text": "HELLO", "length": 5})
        self.assertEqual(output.model_dump(), {"text": "HELLO", "length": 5})
        self.assertEqual(AgentTask.model_validate_json(task.model_dump_json()).task_id, "contract-1")
        with self.assertRaises(ValidationError):
            agent.validate_input(self.make_task("contract-2", text=""))
        with self.assertRaises(ValidationError):
            agent.validate_output({"text": "missing-length"})

    def test_lifecycle_accepts_valid_transitions_and_rejects_invalid_ones(self) -> None:
        task = self.make_task("lifecycle-1")
        task.transition_to(TaskStatus.QUEUED)
        task.transition_to(TaskStatus.RUNNING)
        task.transition_to(TaskStatus.COMPLETED)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNotNone(task.started_at)
        self.assertIsNotNone(task.completed_at)
        with self.assertRaises(ValueError):
            task.transition_to(TaskStatus.RUNNING)
        with self.assertRaises(ValueError):
            task.status = TaskStatus.RUNNING

    def test_successful_execution_persists_result_and_ordered_correlated_events(self) -> None:
        agent = EchoAgent()
        result = self.make_orchestrator(agent).execute(self.make_task("success-1"))
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(result.output_data, {"text": "HELLO", "length": 5})
        self.assertEqual(agent.last_task_context, {"source": "unit-test"})

        persisted_task = self.db.get_agent_task("success-1")
        self.assertIsNotNone(persisted_task)
        self.assertEqual(persisted_task.status, TaskStatus.COMPLETED)
        events = self.db.list_agent_events("success-1")
        self.assertEqual(
            [event.event_type for event in events],
            ["task_created", "task_queued", "agent_started", "agent_completed"],
        )
        self.assertTrue(all(event.correlation_id == "correlation-success-1" for event in events))
        self.assertEqual(events[-1].payload["status"], "completed")
        reopened = Database(self.db_path)
        self.assertEqual(reopened.get_agent_task("success-1").status, TaskStatus.COMPLETED)
        self.assertEqual(len(reopened.list_agent_events("success-1")), 4)
        persisted_result = reopened.get_agent_result("success-1")
        self.assertEqual(persisted_result.output_data, {"text": "HELLO", "length": 5})
        stale_running = AgentTask(
            task_id="success-1",
            agent_id="test.echo",
            input_data={"text": "stale"},
            correlation_id="correlation-success-1",
            status=TaskStatus.RUNNING,
        )
        with self.assertRaises(ValueError):
            reopened.update_agent_task(stale_running)

    def test_invalid_agent_input_returns_failed_result_without_running_agent_logic(self) -> None:
        result = self.make_orchestrator(EchoAgent()).execute(
            AgentTask(
                task_id="invalid-input-1",
                agent_id="test.echo",
                input_data={"unexpected": True},
                correlation_id="correlation-invalid-input-1",
            )
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.error.error_type, "ValidationError")
        self.assertEqual(self.db.get_agent_task("invalid-input-1").status, TaskStatus.FAILED)

    def test_failed_execution_preserves_error_and_failed_state(self) -> None:
        result = self.make_orchestrator(FailingAgent()).execute(self.make_task("failure-1", "test.failing"))
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.error_type, "RuntimeError")
        self.assertIn("intentional test failure", result.error.message)
        self.assertEqual(self.db.get_agent_task("failure-1").status, TaskStatus.FAILED)
        self.assertEqual(self.db.get_agent_result("failure-1").error.error_type, "RuntimeError")
        self.assertEqual(self.db.list_agent_events("failure-1")[-1].event_type, "agent_failed")

    def test_invalid_agent_output_fails_closed(self) -> None:
        result = self.make_orchestrator(InvalidOutputAgent()).execute(
            self.make_task("invalid-output-1", "test.invalid-output")
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.error.error_type, "ValidationError")
        self.assertEqual(self.db.get_agent_task("invalid-output-1").status, TaskStatus.FAILED)

    def test_repeated_task_id_is_rejected_and_distinct_ids_are_isolated(self) -> None:
        orchestrator = self.make_orchestrator(EchoAgent())
        first = orchestrator.execute(self.make_task("repeat-1", text="one"))
        self.assertEqual(first.output_data["text"], "ONE")
        with self.assertRaises(Exception):
            orchestrator.execute(self.make_task("repeat-1", text="two"))
        second = orchestrator.execute(self.make_task("repeat-2", text="two"))
        self.assertEqual(second.output_data["text"], "TWO")
        self.assertEqual(len(self.db.list_agent_events("repeat-1")), 4)
        self.assertEqual(len(self.db.list_agent_events("repeat-2")), 4)

    def test_database_rejects_orphan_agent_event_with_foreign_keys(self) -> None:
        with self.assertRaises(Exception):
            self.db.append_agent_event(
                AgentEvent(
                    event_id="orphan-event",
                    task_id="missing-task",
                    agent_id="test.echo",
                    event_type="agent_started",
                    correlation_id="orphan-correlation",
                )
            )

    def test_atomic_task_creation_rolls_back_when_first_event_fails(self) -> None:
        rollback_db = RollbackEventDatabase(":memory:")
        registry = AgentRegistry()
        registry.register(EchoAgent())
        orchestrator = AgentOrchestrator(registry, ExecutionContext(db=rollback_db))
        with self.assertRaises(OSError):
            orchestrator.execute(self.make_task("rollback-task"))
        self.assertIsNone(rollback_db.get_agent_task("rollback-task"))
        self.assertEqual(rollback_db.list_agent_events("rollback-task"), [])

    def test_provider_unavailable_and_provider_errors_are_explicit(self) -> None:
        with self.assertRaises(ProviderUnavailableError):
            ExecutionContext(db=self.db).require_provider()
        config = ProviderConfig(provider_id="future-local", timeout_seconds=10)
        self.assertEqual(config.provider_id, "future-local")
        with self.assertRaises(ProviderTimeoutError):
            LLMAdapterProvider(ErrorAdapter(TimeoutError("timeout"))).generate("prompt")
        with self.assertRaises(ProviderExecutionError):
            LLMAdapterProvider(ErrorAdapter(ValueError("provider failed"))).generate("prompt")

    def test_execution_context_dependencies_are_isolated(self) -> None:
        other_db = Database(":memory:")
        first_context = ExecutionContext(db=self.db, config={"name": "first"})
        second_context = ExecutionContext(db=other_db, config={"name": "second"})
        self.assertIsNot(first_context.db, second_context.db)
        self.assertNotEqual(first_context.config["name"], second_context.config["name"])
        first_context.execution_metadata["local"] = True
        self.assertNotIn("local", second_context.execution_metadata)

    def test_existing_workflow_database_remains_usable_after_agent_schema_init(self) -> None:
        conn = self.db.get_connection()
        try:
            product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            self.assertEqual(product_count, 0)
            table_names = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
        finally:
            conn.close()
        self.assertIn("products", table_names)
        self.assertIn("agent_tasks", table_names)
        self.assertIn("agent_events", table_names)


if __name__ == "__main__":
    unittest.main()
