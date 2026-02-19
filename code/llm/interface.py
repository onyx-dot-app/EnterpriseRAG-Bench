from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Union


@dataclass
class ToolCall:
    """Represents a tool call made by the LLM."""
    name: str
    args: dict[str, str]


class LLMInterface(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def generate(self, prompt: str) -> Union[str, ToolCall]:
        """
        Generate a response from the LLM.

        Args:
            prompt: The input prompt.

        Returns:
            Either a text response (str) or a ToolCall.
        """
        pass
