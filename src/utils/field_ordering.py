"""Utility for ensuring correct field ordering in document JSON files."""

import json
from typing import Any

# Fields that should appear at the end of the document, in this order
TRAILING_FIELDS = ["title_field_name", "content_field_names", "dataset_doc_uuid"]

# All fields added programmatically (not part of original document content).
# These must never be shown to an LLM that is generating or reasoning about
# document contents.
METADATA_FIELDS = {
    "title_field_name",
    "content_field_names",
    "dataset_doc_uuid",
    "dataset_noise_document",
}


def strip_metadata_fields(document: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *document* with all programmatic metadata fields removed.

    This is intended for preparing document content before sending it to an LLM
    so that metadata like ``dataset_doc_uuid`` never leaks into prompts.
    """
    return {k: v for k, v in document.items() if k not in METADATA_FIELDS}


def load_file_without_metadata(file_path: str) -> str:
    """Load a JSON document file and return it as a JSON string without metadata fields.

    Convenience wrapper that loads, strips metadata, and re-serializes.
    """
    with open(file_path) as f:
        document: dict[str, Any] = json.load(f)
    return json.dumps(strip_metadata_fields(document), indent=2)


def reorder_document_fields(document: dict[str, Any]) -> dict[str, Any]:
    """
    Reorder document fields to ensure trailing fields are at the end.

    The order of trailing fields is:
    1. title_field_name
    2. content_field_names
    3. dataset_doc_uuid (always last)

    Args:
        document: The document dictionary to reorder.

    Returns:
        A new dictionary with fields in the correct order.
    """
    # Separate regular fields from trailing fields
    regular_fields = {}
    trailing_values = {}

    for key, value in document.items():
        if key in TRAILING_FIELDS:
            trailing_values[key] = value
        else:
            regular_fields[key] = value

    # Build the result with regular fields first
    result = dict(regular_fields)

    # Add trailing fields in the correct order
    for field in TRAILING_FIELDS:
        if field in trailing_values:
            result[field] = trailing_values[field]

    return result


def needs_reordering(document: dict[str, Any]) -> bool:
    """
    Check if a document needs field reordering.

    Args:
        document: The document dictionary to check.

    Returns:
        True if the document needs reordering, False otherwise.
    """
    keys = list(document.keys())

    # Find positions of trailing fields that exist in the document
    trailing_positions = []
    for field in TRAILING_FIELDS:
        if field in keys:
            trailing_positions.append((keys.index(field), field))

    if not trailing_positions:
        return False

    # Check if trailing fields are at the end and in correct order
    num_trailing = len(trailing_positions)
    expected_start = len(keys) - num_trailing

    for i, (pos, field) in enumerate(trailing_positions):
        expected_pos = expected_start + i
        if pos != expected_pos:
            return True

    # Check if they're in the correct relative order
    present_trailing = [f for f in TRAILING_FIELDS if f in keys]
    actual_trailing = [f for f in keys if f in TRAILING_FIELDS]

    return present_trailing != actual_trailing
