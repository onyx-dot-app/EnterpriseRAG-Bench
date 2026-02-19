from typing import Any

from src.tools.interface import ToolInterface


class ToolRunner:
    """Runs tools by name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolInterface] = {}

    def register(self, tool: ToolInterface) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def run(self, name: str, **args: Any) -> str:
        """
        Run a tool by name.

        Args:
            name: The tool name.
            **args: Arguments to pass to the tool.

        Returns:
            The tool result as a string.
        """
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'"

        return self._tools[name].execute(**args)

    @property
    def available_tools(self) -> list[str]:
        """List available tool names."""
        return list(self._tools.keys())
