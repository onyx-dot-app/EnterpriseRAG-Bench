from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any

from src.tools.exceptions import ToolTerminationSignal
from src.tools.interface import ToolInterface

TOOL_TIMEOUT_SECONDS = 30


class ToolRunner:
    """Runs tools by name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolInterface] = {}

    def register(self, tool: ToolInterface) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def run(self, name: str, **args: Any) -> str:
        """
        Run a tool by name with a timeout.

        Args:
            name: The tool name.
            **args: Arguments to pass to the tool.

        Returns:
            The tool result as a string.
        """
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'"

        tool = self._tools[name]

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(tool.execute, **args)
            try:
                return future.result(timeout=TOOL_TIMEOUT_SECONDS)
            except ToolTerminationSignal:
                raise
            except TimeoutError:
                return (
                    f"Error: Tool '{name}' timed out after {TOOL_TIMEOUT_SECONDS}s. "
                    f"Reduce the scope of the operation and try again."
                )
            except Exception:
                raise

    @property
    def available_tools(self) -> list[str]:
        """List available tool names."""
        return list(self._tools.keys())
