"""Provider-neutral AI contract for the hybrid strategy.

No network or paid provider is implemented here.  Existing ``LLMAdapter``
implementations can be wrapped when explicitly configured by the caller.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from affiliate_factory.llm import LLMAdapter


class ProviderError(RuntimeError):
    """Base class for provider failures visible to an agent."""


class ProviderUnavailableError(ProviderError):
    """Raised when no configured provider or credentials are available."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider cannot finish within its configured timeout."""


class ProviderExecutionError(ProviderError):
    """Raised when a provider returns an execution error."""


class ProviderConfig(BaseModel):
    """Provider settings kept separate from agent definitions."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str
    model: str | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)
    credentials_env: str | None = None


class AIProvider(ABC):
    """Stable interface future local and external providers must implement."""

    provider_id: str

    @abstractmethod
    def generate(self, prompt: str, *, timeout_seconds: float | None = None) -> str:
        """Generate text or raise a typed ``ProviderError``."""


class UnavailableAIProvider(AIProvider):
    """Explicit default that prevents accidental unconfigured API calls."""

    provider_id = "unavailable"

    def generate(self, prompt: str, *, timeout_seconds: float | None = None) -> str:
        raise ProviderUnavailableError("No AI provider is configured")


class LLMAdapterProvider(AIProvider):
    """Adapter for the existing manual/local ``LLMAdapter`` contract."""

    def __init__(self, adapter: LLMAdapter, provider_id: str = "llm-adapter") -> None:
        self.adapter = adapter
        self.provider_id = provider_id

    def generate(self, prompt: str, *, timeout_seconds: float | None = None) -> str:
        try:
            return self.adapter.generate(prompt)
        except TimeoutError as exc:
            raise ProviderTimeoutError("AI provider timed out") from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderExecutionError(f"AI provider execution failed: {exc}") from exc
