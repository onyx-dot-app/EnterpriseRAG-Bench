import os
from collections.abc import Callable

from src.tools import RM_TOOL
from src.tools.interface import ToolInterface

# Function type that returns the list of deletable paths
DeletablePathsFunc = Callable[[], list[str]]


class RmTool(ToolInterface):
    """Tool for removing files, restricted to files created in the current session."""

    def __init__(
        self,
        base_dir: str | None = None,
        get_deletable_paths: DeletablePathsFunc | None = None,
        display_name: str | None = None,
    ) -> None:
        """
        Initialize the RmTool.

        Args:
            base_dir: Base directory for file operations. Paths will be resolved
                relative to this directory.
            get_deletable_paths: Function that returns the list of paths that can be
                deleted (typically from a JsonDocumentWriteTool). Paths should be relative
                to base_dir (e.g., "confluence/doc.json").
            display_name: Name to show in schema description (defaults to basename of base_dir).
        """
        self._base_dir = base_dir
        self._get_deletable_paths = get_deletable_paths
        self._deleted_paths: list[str] = []
        self._display_name = display_name or (
            os.path.basename(base_dir) if base_dir else None
        )

    @property
    def name(self) -> str:
        return RM_TOOL

    @property
    def deleted_paths(self) -> list[str]:
        """Return list of paths that were successfully deleted."""
        return self._deleted_paths.copy()

    def _normalize_path(self, path: str) -> str:
        """Normalize path by stripping base dir prefix if present."""
        if not self._base_dir:
            return path
        path = path.lstrip("/")
        base_name = os.path.basename(self._base_dir)
        if path.startswith(f"{base_name}/"):
            path = path[len(base_name) + 1 :]
        elif path == base_name:
            path = ""
        return path

    @property
    def schema(self) -> dict:
        description = "Remove a file"
        if self._display_name:
            description += f" under {self._display_name}"
        return {
            "type": "function",
            "name": self.name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path of the file to remove",
                    },
                },
                "required": ["file_path"],
            },
        }

    def execute(self, file_path: str) -> str:  # type: ignore[override]
        """
        Remove a file if it was created in the current session.

        Args:
            file_path: The path of the file to remove.

        Returns:
            Success or error message.
        """
        if not file_path:
            return "Error: No file path provided"

        # Normalize the path
        normalized = self._normalize_path(file_path)

        # Check if this file is in the deletable paths
        if self._get_deletable_paths:
            deletable = self._get_deletable_paths()
            # Deletable paths are stored as "sources/..." so we need to check both formats
            is_deletable = (
                normalized in deletable
                or f"sources/{normalized}" in deletable
                or file_path in deletable
            )
            if not is_deletable:
                return (
                    f"Error: Cannot delete '{file_path}'. "
                    "You can only delete files that you created in this session. "
                    f"Deletable files: {deletable}"
                )

        # Build full path
        if self._base_dir:
            if ".." in normalized:
                return "Error: Path cannot contain '..'"
            full_path = os.path.join(self._base_dir, normalized)
        else:
            full_path = file_path

        # Check if file exists
        if not os.path.exists(full_path):
            return f"Error: File not found: {file_path}"

        # Check it's a file, not a directory
        if os.path.isdir(full_path):
            return f"Error: '{file_path}' is a directory, not a file"

        try:
            os.remove(full_path)
            self._deleted_paths.append(normalized)
            return f"Successfully removed {file_path}"
        except Exception as e:
            return f"Error removing {file_path}: {e}"
