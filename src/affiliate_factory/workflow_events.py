"""Event sinks for workflow execution observability."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from affiliate_factory.workflow_contracts import WorkflowEvent

if TYPE_CHECKING:
    from affiliate_factory.db import Database


class WorkflowEventSink(ABC):
    @abstractmethod
    def publish(self, event: WorkflowEvent) -> None:
        """Publish one validated workflow event."""


class InMemoryWorkflowEventSink(WorkflowEventSink):
    """Test/local observer sink; it intentionally has no database transaction."""

    def __init__(self) -> None:
        self.events: list[WorkflowEvent] = []

    def publish(self, event: WorkflowEvent) -> None:
        self.events.append(event)


class DatabaseWorkflowEventSink(WorkflowEventSink):
    """SQLite event sink used by default for durable workflow monitoring."""

    def __init__(self, db: "Database") -> None:
        self.db = db

    def publish(self, event: WorkflowEvent) -> None:
        self.db.append_workflow_event(event)
