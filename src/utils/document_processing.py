"""Utility for processing written document files (labeling and UUID)."""

import os

from src.utils.dataset_id import add_dataset_doc_uuid
from src.utils.field_labeling import label_single_document


def process_written_document(
    file_path: str, quiet: bool = True
) -> tuple[bool, str | None]:
    """
    Add labels and UUID to a written document.

    This function should be called after a document has been written and validated.
    It adds field labels (title_field_name, content_field_names) and a unique
    dataset_doc_uuid to the document.

    Args:
        file_path: Path to the written JSON file.
        quiet: If True, suppress LLM status output for labeling.

    Returns:
        (success, error_message) tuple.
    """
    if not os.path.exists(file_path):
        return (False, f"File not found: {file_path}")

    try:
        # Add field labels
        label_single_document(file_path, quiet=quiet)

        # Add dataset_doc_uuid
        add_dataset_doc_uuid(file_path)

        return (True, None)
    except Exception as e:
        return (False, str(e))
