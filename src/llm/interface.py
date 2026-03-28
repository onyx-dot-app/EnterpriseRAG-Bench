from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any, Literal

from pydantic import BaseModel


ReasoningLevel = Literal["low", "medium", "high"] | None


class ToolCall(BaseModel):
    """Represents a tool call made by the LLM."""

    name: str
    args: dict[str, Any]
    call_id: str


class Message(BaseModel):
    """A message in the conversation."""

    role: str  # "system", "user", "assistant", "tool_call", "tool_result"
    content: str
    # For tool_call messages
    tool_call: ToolCall | None = None
    # For tool_result messages
    call_id: str | None = None


class LLMInterface(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def generate(
        self, messages: list[Message]
    ) -> Generator[str | ToolCall, None, None]:
        """
        Generate a streaming response from the LLM.

        Args:
            messages: The conversation history.

        Yields:
            String chunks for text responses, or a single ToolCall at the end.
        """
        pass
