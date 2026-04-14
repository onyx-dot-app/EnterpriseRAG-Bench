"""Tool for removing directories."""

import os
import shutil

from src.tools import RMDIR_TOOL
from src.tools.interface import ToolInterface


class RmdirTool(ToolInterface):
    """Tool for removing directories."""

    def __init__(self, base_dir: str):
        """
        Initialize the RmdirTool.

        Args:
            base_dir: Base directory under which directories can be removed.
        """
        self._base_dir = base_dir

    @property
    def name(self) -> str:
        return RMDIR_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": f"Remove a directory under {self._base_dir}. Removes the directory and all its contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to remove (relative to base directory)",
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
        Remove a directory.

        Args:
            path: The directory path to remove (relative to base directory).

        Returns:
            Success or error message.
        """
        path = self._normalize_path(path)

        if ".." in path:
            return "Error: Path cannot contain '..'"

        if not path:
            return "Error: Cannot remove the base directory"

        full_path = os.path.join(self._base_dir, path)

        if not os.path.exists(full_path):
            return f"Error: Directory does not exist: {full_path}"

        if not os.path.isdir(full_path):
            return f"Error: Path is not a directory: {full_path}"

        try:
            shutil.rmtree(full_path)
            return f"Successfully removed directory: {full_path}"
        except Exception as e:
            return f"Error removing directory {full_path}: {e}"
