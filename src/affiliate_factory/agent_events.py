"""Event sinks for observable agent execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from affiliate_factory.agent_contracts import AgentEvent

if TYPE_CHECKING:
    from affiliate_factory.db import Database


class AgentEventSink(ABC):
    """Small dependency-injection boundary for lifecycle events."""

    @abstractmethod
    def publish(self, event: AgentEvent) -> None:
        """Publish one already-validated event."""


class InMemoryAgentEventSink(AgentEventSink):
    """Deterministic sink useful for isolated tests and local observers."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def publish(self, event: AgentEvent) -> None:
        self.events.append(event)


class DatabaseAgentEventSink(AgentEventSink):
    """Persist agent events through the existing SQLite repository."""

    def __init__(self, db: "Database") -> None:
        self.db = db

    def publish(self, event: AgentEvent) -> None:
        self.db.append_agent_event(event)
