"""Schema for project enrichment output validation."""

import json
import os
import subprocess

from pydantic import BaseModel, field_validator

from src.llm import get_llm
from src.llm.interface import Message
from src.prompts.path_recovery import PATH_RECOVERY_PROMPT


class ProjectFile(BaseModel):
    """Schema for a file entry in project enrichment."""

    path: str
    description: str

    @field_validator("path")
    @classmethod
    def validate_path_starts_with_sources(cls, v: str) -> str:
        """Validate path starts with 'sources/'."""
        if not v.startswith("sources/"):
            raise ValueError("path must start with 'sources/'")
        return v


class ProjectEnrichment(BaseModel):
    """Schema for project enrichment output."""

    description: str
    files: list[ProjectFile]

    @field_validator("files")
    @classmethod
    def validate_files_not_empty(cls, v: list[ProjectFile]) -> list[ProjectFile]:
        """Validate that files list is not empty."""
        if not v:
            raise ValueError("files list cannot be empty")
        return v


# Note: Curly braces are doubled to escape them for use in .format() calls
EXPECTED_FORMAT = """
{{
  "description": "A detailed description of the project: goals, scope, stakeholders, timeline, and how it fits within the company context.",
  "files": [
    {{
      "path": "sources/relative/path/to/file.json",
      "description": "A brief description of what this file will contain or discuss (topics, decisions, artifacts, etc.)."
    }}
  ]
}}
""".strip()

# Unescaped version for display/validation purposes
EXPECTED_FORMAT_UNESCAPED = """
{
  "description": "A detailed description of the project: goals, scope, stakeholders, timeline, and how it fits within the company context.",
  "files": [
    {
      "path": "sources/relative/path/to/file.json",
      "description": "A brief description of what this file will contain or discuss (topics, decisions, artifacts, etc.)."
    }
  ]
}
""".strip()


EXPECTED_FORMAT_DESCRIPTION = """
- "description": Expand on the project with enough details to guide document creation (objectives, key phases, roles involved, deliverables, constraints).
- "files": List each hypothetical document. Each entry has:
  - "path": File path starting from `sources/` (e.g. `sources/confluence/engineering/design-doc.json`). CRITICAL: THIS MUST BE A VALID PATH STARTING WITH 'sources/' and the file must be a .json file.
  - "description": What the file will loosely contain or discuss (e.g. "Kickoff meeting notes: attendees, agenda, decisions, action items").
""".strip()


def validate_project_enrichment(content: str) -> str | None:
    """
    Validate project enrichment JSON content.

    Args:
        content: The JSON content to validate.

    Returns:
        None if valid, error message string if invalid.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return f"Invalid JSON syntax: {e}"

    try:
        ProjectEnrichment.model_validate(data)
    except Exception as e:
        return f"Schema validation failed: {e}"

    return None


def parse_project_enrichment(content: str) -> ProjectEnrichment:
    """
    Parse and validate project enrichment JSON content.

    Args:
        content: The JSON content to parse.

    Returns:
        Validated ProjectEnrichment object.

    Raises:
        ValueError: If content is invalid.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON syntax: {e}")

    return ProjectEnrichment.model_validate(data)


def normalize_path(path: str) -> str:
    """
    Normalize a path to ensure it starts with 'sources/' and has single .json extension.

    Handles cases like:
        - ./sources/foo -> sources/foo
        - /sources/foo -> sources/foo
        - sources/foo -> sources/foo (unchanged)
        - foo/bar -> sources/foo/bar (adds prefix)
        - foo.pdf.json -> foo.json (strips extra extensions)
        - foo.doc.json -> foo.json
    """
    # Strip leading whitespace
    path = path.strip()

    # Handle ./sources/ prefix
    if path.startswith("./sources/"):
        path = path[2:]  # Remove "./"

    # Handle /sources/ prefix
    if path.startswith("/sources/"):
        path = path[1:]  # Remove leading "/"

    # Handle ./ prefix without sources
    if path.startswith("./"):
        path = path[2:]

    # Handle leading /
    if path.startswith("/"):
        path = path[1:]

    # Add sources/ prefix if missing
    if not path.startswith("sources/"):
        path = "sources/" + path

    # Clean up multiple extensions - keep only .json
    # e.g., "file.pdf.json" -> "file.json", "file.doc.json" -> "file.json"
    # Strip everything after the first . and add .json if .json was in the string
    dir_part, filename = os.path.split(path)
    if ".json" in filename and "." in filename:
        # Take everything before the first dot, then add .json
        base = filename.split(".")[0]
        filename = base + ".json"
        path = os.path.join(dir_part, filename) if dir_part else filename

    return path


def get_sources_tree(base_dir: str, max_depth: int = 4) -> str:
    """Get a tree representation of the sources directory, rooted at 'sources/'."""
    sources_dir = os.path.join(base_dir, "sources")
    try:
        result = subprocess.run(
            ["tree", "-L", str(max_depth), "--noreport", sources_dir],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        # Replace the full path with just "sources" so LLM sees correct paths
        # e.g., "data_clean/sources" -> "sources"
        output = output.replace(sources_dir, "sources", 1)
        return output
    except Exception:
        # Fallback: simple directory listing
        lines = ["sources/"]
        for root, dirs, files in os.walk(sources_dir):
            # Get path relative to sources_dir
            rel_path = os.path.relpath(root, sources_dir)
            if rel_path == ".":
                level = 0
            else:
                level = rel_path.count(os.sep) + 1
            if level >= max_depth:
                continue
            if rel_path != ".":
                indent = "  " * level
                lines.append(f"{indent}{os.path.basename(root)}/")
            for file in files:
                indent = "  " * (level + 1)
                lines.append(f"{indent}{file}")
        return "\n".join(lines)


def recover_path(incorrect_path: str, base_dir: str) -> str | None:
    """
    Use LLM to recover a correct path from an incorrect one.

    Args:
        incorrect_path: The path that doesn't exist.
        base_dir: Base directory containing sources/.

    Returns:
        Recovered path if successful, None otherwise.
    """
    valid_paths_tree = get_sources_tree(base_dir)

    prompt = PATH_RECOVERY_PROMPT.format(
        incorrect_path=incorrect_path,
        valid_paths_tree=valid_paths_tree,
    )

    llm = get_llm()
    messages = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    # Extract path from response - look for sources/ pattern
    response = response.strip()

    # Try to find a path in the response
    for line in response.split("\n"):
        line = line.strip().strip("`").strip()
        if "sources/" in line:
            # Extract the path starting from sources/
            idx = line.find("sources/")
            candidate = line[idx:].split()[0].strip("\"'`,.")
            return normalize_path(candidate)

    # If response itself looks like a path
    if response.startswith("sources/") or "./sources/" in response:
        return normalize_path(response.split()[0].strip("\"'`,."))

    return None


def is_valid_path(path: str, base_dir: str) -> bool:
    """
    Check if a path is valid for a planned document.

    A path is valid if its parent directory exists (since the file
    will be created later).

    Args:
        path: The path like "sources/confluence/foo/bar.json".
        base_dir: Base directory to resolve paths against.

    Returns:
        True if the parent directory exists.
    """
    full_path = os.path.join(base_dir, path)
    parent_dir = os.path.dirname(full_path)
    return os.path.isdir(parent_dir)


def filter_invalid_paths(
    enrichment: ProjectEnrichment,
    base_dir: str,
) -> ProjectEnrichment:
    """
    Filter out files with invalid parent directories.
    Attempts to recover invalid paths using LLM.

    Since these are planned documents (not yet created), we validate
    that the parent directory exists, not the file itself.

    Args:
        enrichment: The ProjectEnrichment to filter.
        base_dir: Base directory to resolve paths against.
                  Paths in enrichment are like "sources/..." and base_dir
                  should be the parent of "sources/".

    Returns:
        New ProjectEnrichment with only valid file paths.

    Raises:
        ValueError: If all files are filtered out (no valid paths).
    """
    valid_files: list[ProjectFile] = []

    for file in enrichment.files:
        # Normalize the path first
        normalized_path = normalize_path(file.path)

        if is_valid_path(normalized_path, base_dir):
            # Parent directory exists (possibly after normalization)
            if normalized_path != file.path:
                file = ProjectFile(path=normalized_path, description=file.description)
            valid_files.append(file)
        else:
            # Try to recover the path using LLM
            print(f"  Invalid path: {file.path}")
            recovered_path = recover_path(file.path, base_dir)

            if recovered_path:
                if is_valid_path(recovered_path, base_dir):
                    print(f"  Recovered to: {recovered_path}")
                    valid_files.append(
                        ProjectFile(path=recovered_path, description=file.description)
                    )
                else:
                    print(f"  Recovery failed (parent dir doesn't exist): {recovered_path}")
            else:
                print(f"  Recovery failed (no path returned)")

    if not valid_files:
        raise ValueError(
            f"All {len(enrichment.files)} file paths are invalid (parent directories don't exist)"
        )

    return ProjectEnrichment(
        description=enrichment.description,
        files=valid_files,
    )
