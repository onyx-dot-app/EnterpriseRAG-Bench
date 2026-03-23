"""Tool for writing notes to a scratchpad during project enrichment."""

from src.tools import SCRATCHPAD_TOOL
from src.tools.interface import ToolInterface


class ScratchpadTool(ToolInterface):
    """Tool for writing notes to a scratchpad (append by default, can overwrite)."""

    def __init__(self, initial_content: str = ""):
        """
        Initialize the ScratchpadTool.

        Args:
            initial_content: The initial scratchpad content.
        """
        self._content = initial_content

    @property
    def name(self) -> str:
        return SCRATCHPAD_TOOL

    @property
    def content(self) -> str:
        """Returns the current scratchpad content."""
        return self._content

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": (
                "Write notes to a scratchpad. Use this to jot down ideas, partial progress, or any working notes. "
                "By default, content is appended. Set overwrite=true to replace all existing content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The content to write to the scratchpad.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": (
                            "If true, replace all existing content. "
                            "If false (default), append to existing content."
                        ),
                        "default": False,
                    },
                },
                "required": ["content"],
            },
        }

    def execute(self, content: str, overwrite: bool = False) -> str:  # type: ignore[override]
        """
        Write to the scratchpad.

        Args:
            content: The content to write.
            overwrite: If True, replace existing content. If False, append.

        Returns:
            Confirmation message.
        """
        if overwrite:
            self._content = content
            return "Scratchpad overwritten."
        else:
            if self._content:
                self._content += "\n\n" + content
            else:
                self._content = content
            return "Content appended to scratchpad."
