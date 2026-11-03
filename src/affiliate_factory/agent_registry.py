"""Explicit in-process registry for specialist agent implementations."""

from __future__ import annotations

from affiliate_factory.agent import BaseAgent
from affiliate_factory.agent_contracts import AgentMetadata


class AgentRegistryError(RuntimeError):
    """Base error for registry operations."""


class DuplicateAgentError(AgentRegistryError):
    """Raised when an ID is registered more than once."""


class UnknownAgentError(AgentRegistryError):
    """Raised when a task references an unavailable agent ID."""


class AmbiguousCapabilityError(AgentRegistryError):
    """Raised when a capability matches more than one registered agent."""


class AgentRegistry:
    """Simple explicit registry; no plugin loading or dynamic discovery."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        agent_id = agent.metadata.agent_id
        if agent_id in self._agents:
            raise DuplicateAgentError(f"Agent '{agent_id}' is already registered")
        self._agents[agent_id] = agent

    def get(self, agent_id: str) -> BaseAgent:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise UnknownAgentError(f"Unknown agent ID: '{agent_id}'") from exc

    def get_by_capability(self, capability: str) -> BaseAgent:
        """Resolve one capability, rejecting zero or ambiguous matches."""
        matches = [
            agent
            for agent in self._agents.values()
            if capability in agent.metadata.capabilities
        ]
        if not matches:
            raise UnknownAgentError(f"No registered agent provides capability: '{capability}'")
        if len(matches) > 1:
            ids = sorted(agent.metadata.agent_id for agent in matches)
            raise AmbiguousCapabilityError(
                f"Capability '{capability}' is provided by multiple agents: {ids}"
            )
        return matches[0]

    def list_metadata(self) -> list[AgentMetadata]:
        return [self._agents[key].metadata for key in sorted(self._agents)]
