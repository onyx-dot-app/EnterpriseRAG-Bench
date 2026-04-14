"""Tool for searching file contents by text pattern."""

import os
import re

from src.tools import GREP_TOOL
from src.tools.interface import ToolInterface

DEFAULT_LIMIT = 100

TRUNCATION_MESSAGE = (
    "\n\nThe results are cut off due to line limit, "
    "you are encouraged to provide more specific parameters."
)


class GrepTool(ToolInterface):
    """Tool for searching file contents by text pattern."""

    def __init__(
        self,
        base_dir: str,
        display_name: str | None = None,
    ):
        """
        Initialize the GrepTool.

        Args:
            base_dir: Base directory to search within.
            display_name: Name to show in schema description (defaults to basename of base_dir).
        """
        self._base_dir = base_dir
        self._display_name = display_name or os.path.basename(base_dir)

    @property
    def name(self) -> str:
        return GREP_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": (
                f"Search for files containing a text pattern within {self._display_name}. "
                "Returns paths of files whose contents match the pattern."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Text or regex pattern to search for in file contents.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional subdirectory to scope the search "
                            "(e.g., 'slack/general'). Searches all files if omitted."
                        ),
                    },
                },
                "required": ["pattern"],
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

    def execute(self, pattern: str, path: str = "") -> str:  # type: ignore[override]
        """
        Search for files containing a text pattern.

        Args:
            pattern: Text or regex pattern to search for.
            path: Optional subdirectory to scope the search.

        Returns:
            Newline-separated list of matching file paths (relative to base_dir),
            limited to DEFAULT_LIMIT results.
        """
        if path and ".." in path:
            return "Error: Path cannot contain '..'"

        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        search_dir = self._base_dir
        if path:
            path = self._normalize_path(path)
            search_dir = os.path.join(self._base_dir, path)

        if not os.path.isdir(search_dir):
            return f"Error: Directory does not exist: {path}"

        matches: list[str] = []
        for root, _dirs, files in os.walk(search_dir):
            for filename in sorted(files):
                if len(matches) >= DEFAULT_LIMIT:
                    break
                full_path = os.path.join(root, filename)
                try:
                    with open(full_path) as f:
                        content = f.read()
                    if compiled.search(content):
                        rel_path = os.path.relpath(full_path, self._base_dir)
                        matches.append(rel_path)
                except Exception:
                    continue
            if len(matches) >= DEFAULT_LIMIT:
                break

        if not matches:
            return "No files matched the pattern."

        result = "\n".join(sorted(matches))
        if len(matches) >= DEFAULT_LIMIT:
            result += TRUNCATION_MESSAGE
        return result
