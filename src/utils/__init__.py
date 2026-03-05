"""Utility functions."""

from src.utils.agents_md import get_agents_md_for_path, get_agents_md_for_source
from src.utils.cli import confirm_regenerate, confirm_yes_no
from src.utils.dataset_id import add_dataset_doc_uuid, generate_dataset_doc_uuid, get_dataset_doc_uuid
from src.utils.document_content import DocumentFieldError, extract_document_content
from src.utils.dates import get_current_date_formatted
from src.utils.document_processing import process_written_document
from src.utils.field_labeling import (
    get_documents_without_labels,
    label_document_fields,
    label_single_document,
)
from src.utils.field_ordering import needs_reordering, reorder_document_fields
from src.utils.file_io import delete_file, load_file, load_json_file, write_json_file
from src.utils.file_selection import (
    count_json_files,
    dir_has_json_files,
    select_random_file_hierarchical,
)
from src.utils.json_extraction import extract_json_from_response
from src.utils.json_recovery import JsonRecoveryError, try_recover_json
from src.utils.validation import validate_no_nested_dicts

__all__ = [
    "add_dataset_doc_uuid",
    "confirm_regenerate",
    "confirm_yes_no",
    "count_json_files",
    "delete_file",
    "dir_has_json_files",
    "DocumentFieldError",
    "extract_document_content",
    "extract_json_from_response",
    "generate_dataset_doc_uuid",
    "get_agents_md_for_path",
    "get_agents_md_for_source",
    "get_current_date_formatted",
    "get_dataset_doc_uuid",
    "get_documents_without_labels",
    "JsonRecoveryError",
    "label_document_fields",
    "label_single_document",
    "load_file",
    "load_json_file",
    "needs_reordering",
    "process_written_document",
    "reorder_document_fields",
    "select_random_file_hierarchical",
    "try_recover_json",
    "validate_no_nested_dicts",
    "write_json_file",
]
