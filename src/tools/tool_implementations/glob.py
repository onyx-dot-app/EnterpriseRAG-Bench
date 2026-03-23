"""Tool for matching files using glob patterns."""

import glob
import os
import re

from src.tools import GLOB_TOOL
from src.tools.interface import ToolInterface

DEFAULT_LIMIT = 100

TRUNCATION_MESSAGE = (
    "\n\nThe results are cut off due to line limit, "
    "you are encouraged to provide more specific parameters."
)


class GlobTool(ToolInterface):
    """Tool for matching files using glob patterns."""

    def __init__(
        self,
        base_dir: str,
        display_name: str | None = None,
        required_pattern: str | None = None,
        pattern_error_message: str | None = None,
    ):
        """
        Initialize the GlobTool.

        Args:
            base_dir: Base directory to glob within.
            display_name: Name to show in schema description (defaults to basename of base_dir).
            required_pattern: Optional regex pattern that the glob pattern must match.
            pattern_error_message: Custom error message when pattern doesn't match required_pattern.
        """
        self._base_dir = base_dir
        self._display_name = display_name or os.path.basename(base_dir)
        self._required_pattern = (
            re.compile(required_pattern) if required_pattern else None
        )
        self._pattern_error_message = (
            pattern_error_message or "Pattern does not match required format."
        )

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

    def execute(self, pattern: str) -> str:  # type: ignore[override]
        """
        Match files using a glob pattern.

        Args:
            pattern: Glob pattern to match.

        Returns:
            Newline-separated list of matching file paths (relative to base_dir).
        """
        if ".." in pattern:
            return "Error: Pattern cannot contain '..'"

        # Check if pattern matches required regex
        if self._required_pattern and not self._required_pattern.search(pattern):
            return f"Error: {self._pattern_error_message}"

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
                    if len(relative_matches) >= DEFAULT_LIMIT:
                        break

            if not relative_matches:
                return "No files matched the pattern."

            result = "\n".join(relative_matches)
            if len(relative_matches) >= DEFAULT_LIMIT:
                result += TRUNCATION_MESSAGE
            return result
        except Exception as e:
            return f"Error globbing pattern: {e}"
