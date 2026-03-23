"""Utility for generating and adding dataset document UUIDs."""

import uuid

from src.utils.field_ordering import needs_reordering, reorder_document_fields
from src.utils.file_io import load_json_file, write_json_file


def generate_dataset_doc_uuid() -> str:
    """Generate a unique dataset document UUID with dsid_ prefix."""
    return f"dsid_{uuid.uuid4().hex}"


def add_dataset_doc_uuid(file_path: str, fix_ordering: bool = True) -> str:
    """
    Add a dataset_doc_uuid field to a JSON file if it doesn't exist.

    Also ensures correct field ordering (UUID should be last).

    Args:
        file_path: Path to the JSON file.
        fix_ordering: If True, reorder fields to ensure correct ordering.

    Returns:
        The dataset_doc_uuid (existing or newly generated).
    """
    data = load_json_file(file_path)
    needs_write = False

    if "dataset_doc_uuid" not in data:
        data["dataset_doc_uuid"] = generate_dataset_doc_uuid()
        needs_write = True

    # Check and fix field ordering
    if fix_ordering and needs_reordering(data):
        data = reorder_document_fields(data)
        needs_write = True

    if needs_write:
        write_json_file(file_path, data)

    return str(data["dataset_doc_uuid"])


def get_dataset_doc_uuid(file_path: str) -> str | None:
    """
    Get the dataset_doc_uuid from a JSON file.

    Args:
        file_path: Path to the JSON file.

    Returns:
        The dataset_doc_uuid or None if not present.
    """
    data = load_json_file(file_path)
    return data.get("dataset_doc_uuid")
