"""Minimal reusable base interface for specialist agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from pydantic import BaseModel

from affiliate_factory.agent_contracts import AgentMetadata, AgentTask

if TYPE_CHECKING:
    from affiliate_factory.agent_context import ExecutionContext


InputModelT = TypeVar("InputModelT", bound=BaseModel)
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class BaseAgent(ABC, Generic[InputModelT, OutputModelT]):
    """Base contract that validates both sides of an agent boundary."""

    input_model: type[InputModelT]
    output_model: type[OutputModelT]
    metadata: AgentMetadata

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        for attribute in ("input_model", "output_model", "metadata"):
            if not hasattr(cls, attribute):
                raise TypeError(f"Agent subclass must declare {attribute}")

    def validate_input(self, task: AgentTask) -> InputModelT:
        """Validate raw task input against this agent's declared schema."""

        return self.input_model.model_validate(task.input_data)

    def validate_output(self, output: OutputModelT | dict) -> OutputModelT:
        """Validate an agent output before it reaches the orchestrator."""

        return self.output_model.model_validate(output)

    @abstractmethod
    def execute(self, input_data: InputModelT, context: "ExecutionContext") -> OutputModelT:
        """Perform one deterministic unit of work."""
