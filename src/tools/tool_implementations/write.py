import os
import re
from collections.abc import Callable

from src.tools import WRITE_TOOL
from src.tools.interface import ToolInterface

# Validator function type: takes content string, returns error message or None
ValidatorFunc = Callable[[str], str | None]

# Pattern to match control characters (ASCII 0-31 except tab/newline/carriage return, plus DEL 127)
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_control_chars(content: str) -> str:
    """Remove control characters from content, preserving tab, newline, and carriage return."""
    return _CONTROL_CHAR_PATTERN.sub("", content)


class WriteTool(ToolInterface):
    """Tool for writing content to files."""

    def __init__(
        self,
        base_dir: str | None = None,
        file_path_override: str | None = None,
        validator: ValidatorFunc | None = None,
        expected_format: str | None = None,
        display_name: str | None = None,
        allow_create_dirs: bool = True,
    ):
        """
        Initialize the WriteTool.

        Args:
            base_dir: Base directory for all file writes. Paths will be resolved
                relative to this directory.
            file_path_override: If set, all writes go to this path regardless of
                the file_path argument passed to execute().
            validator: Optional function to validate content before writing.
                Should return None if valid, or an error message string if invalid.
            expected_format: Description of expected format to include in error messages.
            display_name: Name to show in schema description (defaults to basename of base_dir).
            allow_create_dirs: If False, will not create new directories. Instead,
                files will be written to the nearest existing parent directory.
        """
        self._base_dir = base_dir
        self._file_path_override = file_path_override
        self._validator = validator
        self._expected_format = expected_format
        self._display_name = display_name or (os.path.basename(base_dir) if base_dir else None)
        self._allow_create_dirs = allow_create_dirs

    @property
    def name(self) -> str:
        return WRITE_TOOL

    def _normalize_path(self, path: str) -> str:
        """Normalize path by stripping base dir prefix if present."""
        if not self._base_dir:
            return path
        path = path.lstrip("/")
        base_name = os.path.basename(self._base_dir)
        if path.startswith(f"{base_name}/"):
            path = path[len(base_name) + 1:]
        elif path == base_name:
            path = ""
        return path

    @property
    def schema(self) -> dict:
        # Responses API format (name at top level, not nested under "function")
        description = "Write content to a file"
        if self._display_name:
            description += f" under {self._display_name}"
        return {
            "type": "function",
            "name": self.name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "The path to write the file to",
                    },
                },
                "required": ["content"],
            },
        }

    def execute(self, content: str, file_path: str = "") -> str:
        """
        Write content to a file.

        Args:
            content: The content to write.
            file_path: The target file path (ignored if file_path_override is set).

        Returns:
            Success or error message.
        """
        target = self._file_path_override or file_path
        if not target:
            return "Error: No file path provided"

        # Handle base_dir if set
        if self._base_dir and not self._file_path_override:
            if ".." in target:
                return "Error: Path cannot contain '..'"
            target = self._normalize_path(target)
            target = os.path.join(self._base_dir, target)

        # Validate content if validator is configured
        if self._validator:
            error = self._validator(content)
            if error:
                msg = f"The file format does not conform to expected. {error}"
                if self._expected_format:
                    msg += f"\n\nExpected format:\n{self._expected_format}"
                return msg

        # Strip control characters from content
        content = _strip_control_chars(content)

        try:
            parent_dir = os.path.dirname(target)
            filename = os.path.basename(target)

            if self._allow_create_dirs:
                # Create parent directories if they don't exist
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
            else:
                # Find the nearest existing parent directory
                original_parent = parent_dir
                while parent_dir and not os.path.exists(parent_dir):
                    parent_dir = os.path.dirname(parent_dir)

                # Fall back to base_dir if no parent exists
                if not parent_dir or not os.path.exists(parent_dir):
                    if self._base_dir and os.path.exists(self._base_dir):
                        parent_dir = self._base_dir
                    else:
                        return f"Error: No existing directory found for {target}"

                # Update target to use the existing parent directory
                if parent_dir != original_parent:
                    target = os.path.join(parent_dir, filename)

            with open(target, "w") as f:
                f.write(content)
            return f"Successfully wrote to {target}"
        except Exception as e:
            return f"Error writing to {target}: {e}"
