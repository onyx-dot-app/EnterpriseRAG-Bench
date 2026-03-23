"""Tool for listing files in a directory."""

import os

from src.tools import LS_TOOL
from src.tools.interface import ToolInterface

DEFAULT_LIMIT = 100

TRUNCATION_MESSAGE = (
    "\n\nThe results are cut off due to line limit, "
    "you are encouraged to provide more specific parameters."
)


class LsTool(ToolInterface):
    """Tool for listing files in a directory using ls."""

    def __init__(
        self,
        base_dir: str,
        display_name: str | None = None,
    ):
        """
        Initialize the LsTool.

        Args:
            base_dir: Base directory to list within.
            display_name: Name to show in schema description (defaults to basename of base_dir).
        """
        self._base_dir = base_dir
        self._display_name = display_name or os.path.basename(base_dir)

    @property
    def name(self) -> str:
        return LS_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": f"List files in a directory within {self._display_name}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory path to list (e.g., 'slack/general', 'confluence/eng').",
                    },
                },
                "required": ["directory"],
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

    def execute(self, directory: str = "") -> str:  # type: ignore[override]
        """
        List files in a directory.

        Args:
            directory: Directory path to list (relative to base_dir).

        Returns:
            Newline-separated list of files and directories.
        """
        if ".." in directory:
            return "Error: Path cannot contain '..'"

        directory = self._normalize_path(directory)
        full_path = (
            os.path.join(self._base_dir, directory) if directory else self._base_dir
        )

        if not os.path.exists(full_path):
            return f"Error: Directory does not exist: {directory}"

        if not os.path.isdir(full_path):
            return f"Error: Path is not a directory: {directory}"

        try:
            entries = sorted(os.listdir(full_path))
            if not entries:
                return "(empty directory)"

            # Mark directories with trailing /
            result = []
            for entry in entries[:DEFAULT_LIMIT]:
                entry_path = os.path.join(full_path, entry)
                if os.path.isdir(entry_path):
                    result.append(f"{entry}/")
                else:
                    result.append(entry)

            output = "\n".join(result)
            if len(entries) > DEFAULT_LIMIT:
                output += TRUNCATION_MESSAGE
            return output
        except Exception as e:
            return f"Error listing directory: {e}"
