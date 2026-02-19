from abc import ABC, abstractmethod


class ToolInterface(ABC):
    """Abstract interface for tools that can be called by an LLM."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the tool."""
        pass

    @abstractmethod
    def execute(self, **args: str) -> str:
        """
        Execute the tool with the given arguments.

        Args:
            **args: Tool-specific arguments.

        Returns:
            The result as a string.
        """
        pass
