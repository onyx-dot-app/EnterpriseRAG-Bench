"""Utility functions."""

from src.utils.cli import confirm_regenerate
from src.utils.dataset_id import add_dataset_doc_uuid, generate_dataset_doc_uuid, get_dataset_doc_uuid
from src.utils.dates import get_current_date_formatted
from src.utils.field_labeling import (
    get_documents_without_labels,
    label_document_fields,
    label_single_document,
)
from src.utils.file_io import delete_file, load_file, load_json_file, write_json_file
from src.utils.json_extraction import extract_json_from_response
from src.utils.validation import validate_no_nested_dicts

__all__ = [
    "add_dataset_doc_uuid",
    "confirm_regenerate",
    "delete_file",
    "extract_json_from_response",
    "generate_dataset_doc_uuid",
    "get_current_date_formatted",
    "get_dataset_doc_uuid",
    "get_documents_without_labels",
    "label_document_fields",
    "label_single_document",
    "load_file",
    "load_json_file",
    "validate_no_nested_dicts",
    "write_json_file",
]
