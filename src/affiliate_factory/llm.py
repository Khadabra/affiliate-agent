"""LLM Adapter interface and ManualPaste implementation."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import Callable


class LLMAdapter(ABC):
    """Abstract interface for LLM operations. Exactly one method."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate response text for the provided prompt."""
        pass


class ManualPaste(LLMAdapter):
    """Manual paste LLM adapter.

    Prints prompt to stdout and reads user-pasted response from stdin or a custom reader.
    Never makes paid API calls or writes secrets.
    """

    def __init__(self, input_reader: Callable[[str], str] | None = None) -> None:
        self._reader = input_reader or input

    def generate(self, prompt: str) -> str:
        separator = "=" * 60
        print(f"\n{separator}\n[PROMPT UNTUK DISALIN KE AI EKSTERNAL]:\n{separator}\n{prompt}\n{separator}")
        print("Silakan tempelkan hasil dari AI di bawah ini:")
        try:
            return self._reader(">> ")
        except EOFError:
            return ""
