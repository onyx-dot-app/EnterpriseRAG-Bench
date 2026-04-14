"""Tool for reading file contents."""

import os

from src.tools import READ_TOOL
from src.tools.interface import ToolInterface


class ReadTool(ToolInterface):
    """Tool for reading file contents."""

    def __init__(self, base_dir: str, display_name: str | None = None):
        """
        Initialize the ReadTool.

        Args:
            base_dir: Base directory for file reads.
            display_name: Name to show in schema description (defaults to basename of base_dir).
        """
        self._base_dir = base_dir
        self._display_name = display_name or os.path.basename(base_dir)

    @property
    def name(self) -> str:
        return READ_TOOL

    @property
    def schema(self) -> dict:
        return self.get_schema()

    def get_schema(self, include_display_name: bool = True) -> dict:
        """Return the OpenAI-format tool schema.

        Args:
            include_display_name: When True the description mentions the
                base directory display name.
        """
        if not include_display_name:
            description = "Read the contents of a file."
        else:
            description = f"Read the contents of a file within {self._display_name}."
        return {
            "type": "function",
            "name": self.name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read (relative to base directory).",
                    },
                },
                "required": ["path"],
            },
        }

    def _normalize_path(self, path: str) -> str:
        """Normalize path by stripping base dir prefix if present."""
        path = path.lstrip("/")
        base_name = os.path.basename(self._base_dir)
        if path.startswith(f"{base_name}/"):
            path = path[len(base_name) + 1 :]
        elif path == base_name:
            path = ""
        return path

    def execute(self, path: str) -> str:  # type: ignore[override]
        """
        Read the contents of a file.

        Args:
            path: Path to the file (relative to base directory).

        Returns:
            File contents or error message.
        """
        if ".." in path:
            return "Error: Path cannot contain '..'"

        path = self._normalize_path(path)
        full_path = os.path.join(self._base_dir, path)

        if not os.path.exists(full_path):
            return f"Error: File does not exist: {path}"

        if not os.path.isfile(full_path):
            return f"Error: Path is not a file: {path}"

        try:
            with open(full_path) as f:
                content = f.read()
            return content
        except Exception as e:
            return f"Error reading file: {e}"
