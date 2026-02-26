"""Tool for matching files using glob patterns."""

import glob
import os

from src.tools import GLOB_TOOL
from src.tools.interface import ToolInterface


class GlobTool(ToolInterface):
    """Tool for matching files using glob patterns."""

    def __init__(self, base_dir: str, display_name: str | None = None):
        """
        Initialize the GlobTool.

        Args:
            base_dir: Base directory to glob within.
            display_name: Name to show in schema description (defaults to basename of base_dir).
        """
        self._base_dir = base_dir
        self._display_name = display_name or os.path.basename(base_dir)

    @property
    def name(self) -> str:
        return GLOB_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": f"Find files matching a glob pattern within {self._display_name}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match (e.g., '**/*.md', '**/agents.md', '*.json').",
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

    def execute(self, pattern: str) -> str:
        """
        Match files using a glob pattern.

        Args:
            pattern: Glob pattern to match.

        Returns:
            Newline-separated list of matching file paths (relative to base_dir).
        """
        if ".." in pattern:
            return "Error: Pattern cannot contain '..'"

        pattern = self._normalize_path(pattern)
        full_pattern = os.path.join(self._base_dir, pattern)

        try:
            matches = glob.glob(full_pattern, recursive=True)
            # Filter to only files (not directories) and make paths relative
            relative_matches = []
            for match in sorted(matches):
                if os.path.isfile(match):
                    rel_path = os.path.relpath(match, self._base_dir)
                    relative_matches.append(rel_path)

            if not relative_matches:
                return "No files matched the pattern."

            return "\n".join(relative_matches)
        except Exception as e:
            return f"Error globbing pattern: {e}"
