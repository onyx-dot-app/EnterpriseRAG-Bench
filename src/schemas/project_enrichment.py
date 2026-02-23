"""Schema for project enrichment output validation."""

import json

from pydantic import BaseModel, field_validator


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
- **description**: Expand on the project with enough detail to guide document creation (objectives, key phases, roles involved, deliverables, constraints).
- **files**: List each hypothetical document. Each entry has:
  - **path**: File path starting from `sources/` (e.g. `sources/confluence/engineering/design-doc.json`). CRITICAL: THIS MUST BE A VALID PATH STARTING WITH 'sources/'.
  - **description**: What the file will loosely contain or discuss (e.g. "Kickoff meeting notes: attendees, agenda, decisions, action items").
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
