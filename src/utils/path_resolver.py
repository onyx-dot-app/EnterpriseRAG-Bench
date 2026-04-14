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

        rel_path = abs_path[len(base_with_sep) :]
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


def validate_source_path(
    file_path: str,
    expected_source_type: str,
) -> str | None:
    """
    Validate that a file path is valid for writing to a specific source type.

    Checks that:
    - Path ends with .json
    - Path starts with the expected source type directory
    - Path has at least source_type/filename structure
    - Parent directory exists
    - File doesn't already exist

    Args:
        file_path: The file path to validate (relative to SOURCES_DIR).
        expected_source_type: The expected source type directory (e.g., "confluence").

    Returns:
        None if valid, error message string if invalid.
    """
    # Normalize the path - strip leading slashes and normalize separators
    normalized = file_path.lstrip("/").replace("\\", "/")

    # Check .json extension
    if not normalized.endswith(".json"):
        return f"File path must end with .json, got: {file_path}"

    # Split into parts
    parts = normalized.split("/")
    if len(parts) < 2:
        return f"File must be in a subdirectory, not directly in sources root. Got: {file_path}"

    # Check that path starts with expected source type
    # Handle cases where path might include "sources/" prefix
    if parts[0] == "sources":
        parts = parts[1:]
        if len(parts) < 2:
            return f"File must be in a subdirectory under {expected_source_type}/. Got: {file_path}"

    if parts[0] != expected_source_type:
        return (
            f"File path must start with '{expected_source_type}/' but got '{parts[0]}/' instead. "
            f"Please write to a directory under {expected_source_type}/."
        )

    # Build the full path and check parent exists
    clean_path = "/".join(parts)
    abs_path = sources_resolver.to_absolute(clean_path)
    parent_dir = os.path.dirname(abs_path)

    if not os.path.isdir(parent_dir):
        return f"Parent directory does not exist: {parent_dir}. Please use an existing directory path."

    # Check file doesn't already exist
    if os.path.exists(abs_path):
        return (
            f"File already exists at {file_path}. Please choose a different filename."
        )

    return None


def normalize_source_path(file_path: str, expected_source_type: str) -> str:
    """
    Normalize a file path to be relative to SOURCES_DIR.

    Handles various input formats:
    - "confluence/docs/file.json" -> "confluence/docs/file.json"
    - "sources/confluence/docs/file.json" -> "confluence/docs/file.json"
    - "/confluence/docs/file.json" -> "confluence/docs/file.json"

    Args:
        file_path: The file path to normalize.
        expected_source_type: The expected source type directory.

    Returns:
        Normalized path relative to SOURCES_DIR.
    """
    # Strip leading slashes and normalize separators
    normalized = file_path.lstrip("/").replace("\\", "/")

    # Remove "sources/" prefix if present
    if normalized.startswith("sources/"):
        normalized = normalized[8:]  # len("sources/") = 8

    return normalized
