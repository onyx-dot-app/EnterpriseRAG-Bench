import os

from src.tools import WRITE_TOOL
from src.tools.interface import ToolInterface


class WriteTool(ToolInterface):
    """Tool for writing content to files."""

    def __init__(self, file_path_override: str | None = None):
        """
        Initialize the WriteTool.

        Args:
            file_path_override: If set, all writes go to this path regardless of
                the file_path argument passed to execute().
        """
        self._file_path_override = file_path_override

    @property
    def name(self) -> str:
        return WRITE_TOOL

    @property
    def schema(self) -> dict:
        # Responses API format (name at top level, not nested under "function")
        return {
            "type": "function",
            "name": self.name,
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "The path to write the file to",
                    },
                },
                "required": ["content"],
            },
        }

    def execute(self, content: str, file_path: str = "") -> str:
        """
        Write content to a file.

        Args:
            content: The content to write.
            file_path: The target file path (ignored if file_path_override is set).

        Returns:
            Success or error message.
        """
        target = self._file_path_override or file_path
        if not target:
            return "Error: No file path provided"

        try:
            # Create parent directories if they don't exist
            parent_dir = os.path.dirname(target)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(target, "w") as f:
                f.write(content)
            return f"Successfully wrote to {target}"
        except Exception as e:
            return f"Error writing to {target}: {e}"
