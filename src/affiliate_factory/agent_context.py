"""Dependency-injected execution context shared by registered agents."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from affiliate_factory.agent_events import AgentEventSink, DatabaseAgentEventSink
from affiliate_factory.agent_provider import AIProvider, ProviderUnavailableError, UnavailableAIProvider
from affiliate_factory.db import Database


@dataclass
class ExecutionContext:
    """Controlled runtime dependencies for one agent execution."""

    db: Database
    config: Mapping[str, Any] = field(default_factory=dict)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("affiliate_factory.agent"))
    provider: AIProvider | None = None
    event_sink: AgentEventSink | None = None
    task_context: Mapping[str, Any] = field(default_factory=dict)
    execution_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_sink is None:
            self.event_sink = DatabaseAgentEventSink(self.db)

    def for_task(self, task_context: Mapping[str, Any]) -> "ExecutionContext":
        """Create an isolated per-task view without mutating shared dependencies."""

        return ExecutionContext(
            db=self.db,
            config=self.config,
            logger=self.logger,
            provider=self.provider,
            event_sink=self.event_sink,
            task_context=dict(task_context),
            execution_metadata=dict(self.execution_metadata),
        )

    def require_provider(self) -> AIProvider:
        """Return a provider or fail explicitly instead of making an implicit call."""

        if self.provider is None:
            raise ProviderUnavailableError("No AI provider is configured for this execution context")
        if isinstance(self.provider, UnavailableAIProvider):
            raise ProviderUnavailableError("No AI provider is configured for this execution context")
        return self.provider
