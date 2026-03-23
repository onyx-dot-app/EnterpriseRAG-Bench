"""Tool for displaying directory tree structure."""

import os

from src.tools import TREE_TOOL
from src.tools.interface import ToolInterface


class TreeTool(ToolInterface):
    """Tool for displaying directory tree structure."""

    def __init__(self, base_dir: str, display_name: str | None = None):
        """
        Initialize the TreeTool.

        Args:
            base_dir: Base directory to show the tree for.
            display_name: Name to show in schema description (defaults to basename of base_dir).
        """
        self._base_dir = base_dir
        self._display_name = display_name or os.path.basename(base_dir)

    @property
    def name(self) -> str:
        return TREE_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": f"Display the directory tree structure under {self._display_name}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional subdirectory path to show tree for (relative to base directory). If not provided, shows entire tree.",
                    },
                    "level": {
                        "type": "integer",
                        "description": "Optional maximum depth to descend into the directory tree. If not provided, shows all levels.",
                    },
                    "filelimit": {
                        "type": "integer",
                        "description": "Optional maximum number of entries to show per directory. If not provided, shows all entries.",
                    },
                },
                "required": [],
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

    def _build_tree(
        self,
        dir_path: str,
        prefix: str = "",
        level: int | None = None,
        filelimit: int | None = None,
        current_depth: int = 0,
    ) -> list[str]:
        """Recursively build tree lines for a directory."""
        lines: list[str] = []

        # Check depth limit
        if level is not None and current_depth >= level:
            return lines

        try:
            entries = sorted(os.listdir(dir_path))
        except PermissionError:
            return [f"{prefix}[Permission Denied]"]

        # Filter to only directories
        dirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]

        # Apply filelimit
        truncated = False
        if filelimit is not None and len(dirs) > filelimit:
            dirs = dirs[:filelimit]
            truncated = True

        for i, name in enumerate(dirs):
            is_last = i == len(dirs) - 1 and not truncated
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{name}/")

            # Recurse into subdirectory
            child_prefix = prefix + ("    " if is_last else "│   ")
            child_path = os.path.join(dir_path, name)
            lines.extend(
                self._build_tree(
                    child_path, child_prefix, level, filelimit, current_depth + 1
                )
            )

        if truncated:
            lines.append(f"{prefix}└── ...")

        return lines

    def execute(  # type: ignore[override]
        self,
        path: str = "",
        level: int | None = None,
        filelimit: int | None = None,
    ) -> str:
        """
        Display directory tree structure.

        Args:
            path: Optional subdirectory path (relative to base directory).
            level: Optional maximum depth to descend into the tree.
            filelimit: Optional maximum number of entries per directory.

        Returns:
            Tree structure as a string.
        """
        path = self._normalize_path(path)

        if ".." in path:
            return "Error: Path cannot contain '..'"

        full_path = os.path.join(self._base_dir, path) if path else self._base_dir

        if not os.path.exists(full_path):
            return f"Error: Directory does not exist: {full_path}"

        if not os.path.isdir(full_path):
            return f"Error: Path is not a directory: {full_path}"

        # Build the tree
        root_name = os.path.basename(full_path) or os.path.basename(self._base_dir)
        lines = [f"{root_name}/"]
        lines.extend(self._build_tree(full_path, level=level, filelimit=filelimit))

        if len(lines) == 1:
            return f"{root_name}/ (empty)"

        return "\n".join(lines)
