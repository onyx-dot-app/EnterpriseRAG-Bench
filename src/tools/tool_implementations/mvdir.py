"""Tool for moving/renaming directories."""

import os
import shutil

from src.tools import MVDIR_TOOL
from src.tools.interface import ToolInterface


class MvdirTool(ToolInterface):
    """Tool for moving/renaming directories."""

    def __init__(self, base_dir: str):
        """
        Initialize the MvdirTool.

        Args:
            base_dir: Base directory under which directories can be moved.
        """
        self._base_dir = base_dir

    @property
    def name(self) -> str:
        return MVDIR_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": f"Move or rename a directory under {self._base_dir}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "The source directory path (relative to base directory)",
                    },
                    "destination": {
                        "type": "string",
                        "description": "The destination directory path (relative to base directory)",
                    },
                },
                "required": ["source", "destination"],
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

    def execute(self, source: str, destination: str) -> str:  # type: ignore[override]
        """
        Move or rename a directory.

        Args:
            source: The source directory path (relative to base directory).
            destination: The destination directory path (relative to base directory).

        Returns:
            Success or error message.
        """
        source = self._normalize_path(source)
        destination = self._normalize_path(destination)

        if ".." in source or ".." in destination:
            return "Error: Paths cannot contain '..'"

        if not source:
            return "Error: Cannot move the base directory"

        source_path = os.path.join(self._base_dir, source)
        dest_path = os.path.join(self._base_dir, destination)

        if not os.path.exists(source_path):
            return f"Error: Source directory does not exist: {source_path}"

        if not os.path.isdir(source_path):
            return f"Error: Source path is not a directory: {source_path}"

        if os.path.exists(dest_path):
            return f"Error: Destination already exists: {dest_path}"

        try:
            # Create parent directories if needed
            dest_parent = os.path.dirname(dest_path)
            if dest_parent:
                os.makedirs(dest_parent, exist_ok=True)

            shutil.move(source_path, dest_path)
            return f"Successfully moved {source_path} to {dest_path}"
        except Exception as e:
            return f"Error moving directory: {e}"
