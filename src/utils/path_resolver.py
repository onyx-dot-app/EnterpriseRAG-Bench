"""Utility for standardizing path handling between absolute and relative formats.

This module provides a PathResolver class that converts between:
- Relative paths: e.g., "sources/confluence/doc.json" (relative to base_dir)
- Absolute paths: e.g., "/full/path/generated_data/sources/confluence/doc.json"

The relative format is what the LLM sees and what gets stored in JSON files.
The absolute format is used for actual filesystem operations.
"""

import os

from src.paths import GENERATED_DATA_DIR, SOURCES_DIR


class PathResolver:
    """Handles conversion between relative and absolute paths.

    Relative paths are relative to `base_dir` (defaults to GENERATED_DATA_DIR).
    Both conversion methods are idempotent - calling to_absolute on an absolute
    path returns it unchanged, and vice versa.

    Example:
        resolver = PathResolver()

        # Convert to absolute for filesystem operations
        abs_path = resolver.to_absolute("sources/confluence/doc.json")
        # -> "/full/path/generated_data/sources/confluence/doc.json"

        # Convert to relative for LLM/storage
        rel_path = resolver.to_relative("/full/path/generated_data/sources/confluence/doc.json")
        # -> "sources/confluence/doc.json"
    """

    def __init__(self, base_dir: str = GENERATED_DATA_DIR) -> None:
        """Initialize the PathResolver.

        Args:
            base_dir: The base directory that relative paths are relative to.
                      Defaults to GENERATED_DATA_DIR.
        """
        self._base_dir = os.path.abspath(base_dir)

    @property
    def base_dir(self) -> str:
        """The absolute path of the base directory."""
        return self._base_dir

    def is_absolute(self, path: str) -> bool:
        """Check if a path is absolute.

        Args:
            path: The path to check.

        Returns:
            True if the path is absolute, False otherwise.
        """
        return os.path.isabs(path)

    def is_relative(self, path: str) -> bool:
        """Check if a path is in relative format.

        Args:
            path: The path to check.

        Returns:
            True if the path is relative, False otherwise.
        """
        return not os.path.isabs(path)

    def to_absolute(self, path: str) -> str:
        """Convert a path to absolute format.

        This method is idempotent - if the path is already absolute,
        it is returned unchanged.

        Args:
            path: The path to convert (relative or absolute).

        Returns:
            The absolute path.
        """
        if os.path.isabs(path):
            return path
        return os.path.join(self._base_dir, path)

    def to_relative(self, path: str) -> str:
        """Convert a path to relative format (relative to base_dir).

        This method is idempotent - if the path is already relative,
        it is returned unchanged.

        Args:
            path: The path to convert (relative or absolute).

        Returns:
            The relative path. Uses forward slashes for consistency.

        Raises:
            ValueError: If the absolute path is not under base_dir.
        """
        if not os.path.isabs(path):
            # Already relative, normalize slashes
            return path.replace("\\", "/")

        # Ensure both paths are normalized for comparison
        abs_path = os.path.abspath(path)
        base_with_sep = self._base_dir + os.sep

        if abs_path == self._base_dir:
            return ""

        if not abs_path.startswith(base_with_sep):
            raise ValueError(
                f"Path '{path}' is not under base directory '{self._base_dir}'"
            )

        rel_path = abs_path[len(base_with_sep):]
        # Normalize to forward slashes for consistency
        return rel_path.replace("\\", "/")

    def exists(self, path: str) -> bool:
        """Check if a path exists on the filesystem.

        Accepts either relative or absolute paths.

        Args:
            path: The path to check.

        Returns:
            True if the path exists, False otherwise.
        """
        return os.path.exists(self.to_absolute(path))

    def is_file(self, path: str) -> bool:
        """Check if a path is an existing file.

        Accepts either relative or absolute paths.

        Args:
            path: The path to check.

        Returns:
            True if the path is an existing file, False otherwise.
        """
        return os.path.isfile(self.to_absolute(path))

    def is_dir(self, path: str) -> bool:
        """Check if a path is an existing directory.

        Accepts either relative or absolute paths.

        Args:
            path: The path to check.

        Returns:
            True if the path is an existing directory, False otherwise.
        """
        return os.path.isdir(self.to_absolute(path))

    def join(self, *parts: str) -> str:
        """Join path components and return a relative path.

        All parts are joined together. If any part is absolute and under
        base_dir, it is converted to relative first.

        Args:
            *parts: Path components to join.

        Returns:
            The joined relative path.
        """
        # Convert any absolute paths to relative first
        relative_parts = []
        for part in parts:
            if os.path.isabs(part):
                try:
                    part = self.to_relative(part)
                except ValueError:
                    pass  # Keep as-is if not under base_dir
            relative_parts.append(part)

        joined = os.path.join(*relative_parts) if relative_parts else ""
        return joined.replace("\\", "/")


# Default resolver instance using GENERATED_DATA_DIR
# Use for paths like "sources/confluence/doc.json"
default_resolver = PathResolver()

# Sources resolver instance using SOURCES_DIR
# Use for paths like "confluence/doc.json" (relative to sources/)
sources_resolver = PathResolver(base_dir=SOURCES_DIR)
