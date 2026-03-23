"""Tool for creating directories."""

import os

from src.tools import MKDIR_TOOL
from src.tools.interface import ToolInterface


class MkdirTool(ToolInterface):
    """Tool for creating directories."""

    def __init__(self, base_dir: str):
        """
        Initialize the MkdirTool.

        Args:
            base_dir: Base directory under which all directories will be created.
        """
        self._base_dir = base_dir

    @property
    def name(self) -> str:
        return MKDIR_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": f"Create a directory under {self._base_dir}. Can create nested directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to create (relative to base directory)",
                    },
                },
                "required": ["path"],
            },
        }

    def execute(self, path: str) -> str:  # type: ignore[override]
        """
        Create a directory.

        Args:
            path: The directory path to create (relative to base directory).

        Returns:
            Success or error message.
        """
        # Sanitize path - prevent escaping base directory
        path = path.lstrip("/")
        if ".." in path:
            return "Error: Path cannot contain '..'"

        # Strip "sources/" prefix if LLM includes it (base_dir already has it)
        base_name = os.path.basename(self._base_dir)
        if path.startswith(f"{base_name}/"):
            path = path[len(base_name) + 1 :]
        elif path == base_name:
            path = ""

        full_path = os.path.join(self._base_dir, path)

        try:
            os.makedirs(full_path, exist_ok=True)
            return f"Successfully created directory: {full_path}"
        except Exception as e:
            return f"Error creating directory {full_path}: {e}"
