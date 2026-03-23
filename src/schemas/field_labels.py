"""Schema for field labeling output validation."""

import json

from pydantic import BaseModel, field_validator


class FieldLabels(BaseModel):
    """Schema for field labels output."""

    title_field_name: str
    content_field_names: list[str]

    @field_validator("content_field_names")
    @classmethod
    def validate_content_field_names_not_empty(cls, v: list[str]) -> list[str]:
        """Validate that content_field_names list is not empty."""
        if not v:
            raise ValueError("content_field_names list cannot be empty")
        return v


# Note: Curly braces are doubled to escape them for use in .format() calls
EXPECTED_FIELD_LABELS_FORMAT = """
{{
  "title_field_name": "title_field_name",
  "content_field_names": ["content_field_name_1", "content_field_name_2", ...]
}}
""".strip()

# Unescaped version for display/validation purposes
EXPECTED_FIELD_LABELS_FORMAT_UNESCAPED = """
{
  "title_field_name": "title_field_name",
  "content_field_names": ["content_field_name_1", "content_field_name_2", ...]
}
""".strip()


def validate_field_labels(content: str) -> str | None:
    """
    Validate field labels JSON content.

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
        FieldLabels.model_validate(data)
    except Exception as e:
        return f"Schema validation failed: {e}"

    return None


def parse_field_labels(content: str) -> FieldLabels:
    """
    Parse and validate field labels JSON content.

    Args:
        content: The JSON content to parse.

    Returns:
        Validated FieldLabels object.

    Raises:
        ValueError: If content is invalid.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON syntax: {e}")

    return FieldLabels.model_validate(data)


def validate_field_labels_against_document(
    field_labels: FieldLabels,
    document: dict,
) -> str | None:
    """
    Validate that the field labels reference existing keys in the document.

    Args:
        field_labels: The parsed field labels.
        document: The document JSON to validate against.

    Returns:
        None if valid, error message string if invalid.
    """
    # Get all keys from document (including nested keys with dot notation)
    doc_keys = set(document.keys())

    # Check title field exists
    if field_labels.title_field_name not in doc_keys:
        return f"title_field_name '{field_labels.title_field_name}' does not exist in document. Available keys: {sorted(doc_keys)}"

    # Check all content fields exist
    for field_name in field_labels.content_field_names:
        if field_name not in doc_keys:
            return f"content_field_name '{field_name}' does not exist in document. Available keys: {sorted(doc_keys)}"

    return None
