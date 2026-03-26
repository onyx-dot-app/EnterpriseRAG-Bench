import json
import os
import re
from collections.abc import Callable

from src.llm import Message, get_llm
from src.prompts.path_recovery import PATH_RECOVERY_PROMPT
from src.tools import WRITE_TOOL
from src.tools.exceptions import ToolTerminationSignal
from src.tools.interface import ToolInterface
from src.utils.directory_tree import get_directory_tree
from src.utils.document_processing import process_written_document
from src.utils.file_io import sanitize_filename, sanitize_path
from src.utils.json_recovery import JsonRecoveryError, try_recover_json
from src.utils.path_resolver import (
    normalize_source_path,
    sources_resolver,
    validate_source_path,
)
from src.utils.validation import validate_no_nested_dicts

# Validator function type: takes content string, returns error message or None
ValidatorFunc = Callable[[str], str | None]

# Pattern to match control characters (ASCII 0-31 except tab/newline/carriage return, plus DEL 127)
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_control_chars(content: str) -> str:
    """Remove control characters from content, preserving tab, newline, and carriage return."""
    return _CONTROL_CHAR_PATTERN.sub("", content)


def _recover_path_with_llm(
    incorrect_path: str,
    base_dir: str,
    quiet: bool = True,
) -> str | None:
    """
    Use LLM to recover a correct path from an incorrect one.

    Args:
        incorrect_path: The path that failed validation.
        base_dir: Base directory for the tree (what LLM sees).
        quiet: If True, suppress LLM output.

    Returns:
        Recovered path if successful, None otherwise.
    """
    valid_paths_tree = get_directory_tree(base_dir)

    prompt = PATH_RECOVERY_PROMPT.format(
        incorrect_path=incorrect_path,
        valid_paths_tree=valid_paths_tree,
    )

    llm = get_llm(quiet=quiet)
    messages = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    response = response.strip()

    # Extract the path from the response
    # Look for patterns that look like file paths
    base_name = os.path.basename(base_dir.rstrip("/"))

    for line in response.split("\n"):
        line = line.strip().strip("`").strip()
        # Check if line contains a path starting with the base directory name
        if f"{base_name}/" in line:
            idx = line.find(f"{base_name}/")
            candidate = line[idx:].split()[0].strip("\"'`,.")
            # Remove the base_name prefix since we want path relative to base_dir
            if candidate.startswith(f"{base_name}/"):
                return candidate[len(base_name) + 1 :]
        # Also check for paths that might already be relative
        if "/" in line and line.endswith(".json"):
            candidate = line.split()[0].strip("\"'`,.")
            if not candidate.startswith("/"):
                return candidate

    return None


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
        # Document JSON parameters:
        is_document_json: bool = False,
        expected_source_type: str | None = None,
        mark_as_noise: bool = False,
        auto_process: bool = False,
        quiet: bool = True,
        llm_path_recovery: bool = False,
        conflict_message: str | None = None,
        terminate_on_success: bool = False,
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
            is_document_json: Enable document JSON validation pipeline (validates path,
                JSON structure, and optionally runs post-processing).
            expected_source_type: Source type for path validation (e.g., "confluence").
                Only used when is_document_json=True.
            mark_as_noise: Add dataset_noise_document: True to the document data.
                Only used when is_document_json=True.
            auto_process: Run field labels + UUID post-processing after successful write.
                Only used when is_document_json=True.
            quiet: Suppress LLM output during processing (for JSON recovery and labeling).
                Only used when is_document_json=True.
            llm_path_recovery: If True, use LLM to attempt to recover invalid paths
                by finding the closest valid directory. Only used when is_document_json=True.
            conflict_message: Custom message to return when a file already exists at the
                target path. If None, a default error message is used.
            terminate_on_success: If True, raise ToolTerminationSignal on successful write
                to end the conversation loop immediately.
        """
        self._base_dir = base_dir
        self._file_path_override = file_path_override
        self._validator = validator
        self._expected_format = expected_format
        self._display_name = display_name or (
            os.path.basename(base_dir) if base_dir else None
        )
        self._allow_create_dirs = allow_create_dirs
        # Document JSON parameters
        self._is_document_json = is_document_json
        self._expected_source_type = expected_source_type
        self._mark_as_noise = mark_as_noise
        self._auto_process = auto_process
        self._quiet = quiet
        self._llm_path_recovery = llm_path_recovery
        self._conflict_message = conflict_message
        self._terminate_on_success = terminate_on_success
        self._written_paths: list[str] = []

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
            path = path[len(base_name) + 1 :]
        elif path == base_name:
            path = ""
        return path

    @property
    def written_paths(self) -> list[str]:
        """Return list of paths written since last reset (document JSON mode only)."""
        return self._written_paths.copy()

    def reset_tracking(self) -> None:
        """Clear the list of written paths."""
        self._written_paths = []

    def remove_path(self, path: str) -> None:
        """Remove a path from tracking (called when file is deleted)."""
        # Try to remove with various formats
        for p in [path, f"sources/{path}"]:
            if p in self._written_paths:
                self._written_paths.remove(p)
                return

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

    def execute(self, content: str, file_path: str = "") -> str:  # type: ignore[override]
        """
        Write content to a file.

        Args:
            content: The content to write.
            file_path: The target file path (ignored if file_path_override is set).

        Returns:
            Success or error message.
        """
        # Document JSON mode: special validation pipeline
        if self._is_document_json:
            return self._execute_document_json(content, file_path)

        target = self._file_path_override or file_path
        if not target:
            return "Error: No file path provided"

        # Sanitize non-ASCII characters in the path (e.g., Cyrillic homoglyphs)
        target = sanitize_path(target)

        # Track relative path for response messages (what the LLM sees)
        response_path = target

        # Handle base_dir if set
        if self._base_dir and not self._file_path_override:
            if ".." in target:
                return "Error: Path cannot contain '..'"
            response_path = self._normalize_path(target)
            target = os.path.join(self._base_dir, response_path)

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
                # Find the nearest existing parent directory that is a leaf
                original_parent = parent_dir
                while parent_dir and not os.path.exists(parent_dir):
                    parent_dir = os.path.dirname(parent_dir)

                # Fall back to base_dir if no parent exists
                if not parent_dir or not os.path.exists(parent_dir):
                    if self._base_dir and os.path.exists(self._base_dir):
                        parent_dir = self._base_dir
                    else:
                        return f"Error: No existing directory found for {target}"

                # Only allow recovery if the parent directory is a leaf (no subdirectories)
                if parent_dir != original_parent:
                    has_subdirs = any(
                        os.path.isdir(os.path.join(parent_dir, entry))
                        for entry in os.listdir(parent_dir)
                    )
                    if has_subdirs:
                        return f"Error: Parent directory does not exist and nearest existing directory '{parent_dir}' is not a leaf directory"
                    target = os.path.join(parent_dir, filename)

            with open(target, "w") as f:
                f.write(content)
            return f"Successfully wrote to {response_path}"
        except Exception as e:
            return f"Error writing to {response_path}: {e}"

    def _execute_document_json(self, content: str, file_path: str) -> str:
        """
        Execute document JSON write with validation pipeline.

        Validates:
        - File path ends with .json
        - Path is under expected source type (if configured)
        - Parent directory exists
        - File doesn't already exist
        - Content is valid JSON (with LLM recovery fallback)
        - JSON has flat structure (no nested dicts)

        After successful write:
        - Tracks written path
        - Optionally runs field labels + UUID post-processing
        """
        if not file_path:
            return (
                "Error: No file path provided. Please specify a valid .json file path."
            )

        # Sanitize non-ASCII characters in the path (e.g., Cyrillic homoglyphs)
        file_path = sanitize_path(file_path)

        # Validate path format using existing utilities
        if self._expected_source_type:
            path_error = validate_source_path(file_path, self._expected_source_type)
            if path_error:
                # Attempt LLM path recovery if enabled
                if self._llm_path_recovery and self._base_dir:
                    if not self._quiet:
                        print(f"\nPath validation failed: {path_error}")
                        print("Attempting LLM path recovery...")
                    recovered = _recover_path_with_llm(
                        file_path, self._base_dir, quiet=self._quiet
                    )
                    if recovered:
                        if not self._quiet:
                            print(f"Recovered path: {recovered}")
                        file_path = recovered
                        # Re-validate the recovered path
                        path_error = validate_source_path(
                            file_path, self._expected_source_type
                        )

                if path_error:
                    return f"Error: {path_error}"

            # Normalize path to be relative to SOURCES_DIR
            normalized_path = normalize_source_path(
                file_path, self._expected_source_type
            )
            abs_path = sources_resolver.to_absolute(normalized_path)

            # Check if file already exists
            if os.path.exists(abs_path):
                return (
                    self._conflict_message
                    or f"Error: File already exists at {file_path}. Please choose a different filename."
                )
        else:
            # Basic validation without source type
            if not file_path.endswith(".json"):
                return f"Error: File path must end with .json, got: {file_path}. Please use a .json extension."

            # Check proper directory structure
            normalized_path = (
                self._normalize_path(file_path) if self._base_dir else file_path
            )
            path_parts = normalized_path.replace("\\", "/").split("/")
            if len(path_parts) < 2:
                return f"Error: File must be in a subdirectory, not directly in sources root. Got: {file_path}"

            # Validate parent directory exists and file doesn't already exist
            if self._base_dir:
                abs_path = os.path.join(self._base_dir, normalized_path)
                parent_dir = os.path.dirname(abs_path)
                if not os.path.isdir(parent_dir):
                    # Attempt LLM path recovery if enabled
                    if self._llm_path_recovery:
                        if not self._quiet:
                            print(f"\nParent directory does not exist: {parent_dir}")
                            print("Attempting LLM path recovery...")
                        recovered = _recover_path_with_llm(
                            file_path, self._base_dir, quiet=self._quiet
                        )
                        if recovered:
                            if not self._quiet:
                                print(f"Recovered path: {recovered}")
                            normalized_path = recovered
                            abs_path = os.path.join(self._base_dir, normalized_path)
                            parent_dir = os.path.dirname(abs_path)

                    if not os.path.isdir(parent_dir):
                        return f"Error: Parent directory does not exist: {parent_dir}. Please use an existing directory path."

                if os.path.exists(abs_path):
                    return (
                        self._conflict_message
                        or f"Error: File already exists at {file_path}. Please choose a different filename."
                    )
            else:
                abs_path = normalized_path

        # Strip control characters
        content = _strip_control_chars(content)

        # Parse and validate JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Attempt JSON recovery using LLM
            try:
                content = try_recover_json(content, quiet=self._quiet)
                data = json.loads(content)
            except JsonRecoveryError as e:
                return f"Error: Invalid JSON and recovery failed: {e}"

        # Validate flat structure (no nested dicts)
        validation_error = validate_no_nested_dicts(data)
        if validation_error:
            return f"Error: {validation_error}. All values must be strings, primitives, or lists of strings/primitives. Please fix and try again."

        # Add noise marker if configured
        if self._mark_as_noise:
            data["dataset_noise_document"] = True

        # Re-serialize JSON
        final_content = json.dumps(data, indent=2)

        # Write the file
        try:
            parent_dir = os.path.dirname(abs_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            with open(abs_path, "w") as f:
                f.write(final_content)
        except Exception as e:
            return f"Error writing to {normalized_path}: {e}"

        # Track the written path (relative to GENERATED_DATA_DIR)
        if self._expected_source_type:
            rel_path = f"sources/{normalized_path}"
        else:
            rel_path = normalized_path
        self._written_paths.append(rel_path)

        # Run post-processing if configured
        if self._auto_process:
            success, error = process_written_document(abs_path, quiet=self._quiet)
            if not success:
                return f"Error processing document: {error}"

        result = f"Successfully wrote to {normalized_path}"
        if self._terminate_on_success:
            raise ToolTerminationSignal(result)
        return result
