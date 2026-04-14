"""Utility functions."""

from src.utils.agents_md import get_agents_md_for_path, get_agents_md_for_source
from src.utils.cli import confirm_regenerate, confirm_yes_no
from src.utils.dataset_id import (
    add_dataset_doc_uuid,
    generate_dataset_doc_uuid,
    get_dataset_doc_uuid,
)
from src.utils.document_content import DocumentFieldError, extract_document_content
from src.utils.document_index import (
    DEFAULT_UUID_INDEX_CACHE_FILE,
    build_uuid_index,
    ensure_uuids_resolved,
    load_document_content_by_uuid,
    load_document_json_by_uuid,
    load_or_build_uuid_index,
    rebuild_uuid_index,
    write_uuid_index_cache,
)
from src.utils.dates import get_current_date_formatted
from src.utils.directory_tree import get_directory_tree
from src.utils.document_processing import process_written_document
from src.utils.field_labeling import (
    get_documents_without_labels,
    label_document_fields,
    label_single_document,
)
from src.utils.field_ordering import (
    load_file_without_metadata,
    needs_reordering,
    reorder_document_fields,
    strip_metadata_fields,
)
from src.utils.file_io import (
    delete_file,
    load_file,
    load_json_file,
    sanitize_filename,
    sanitize_path,
    write_json_file,
)
from src.utils.generation_cache import (
    GenerationCache,
    completeness_cache,
    duplications_cache,
    misc_files_cache,
    projects_cache,
    info_not_found_used_paths_cache,
)
from src.utils.file_selection import (
    collect_json_files_by_size,
    count_json_files,
    dir_has_json_files,
    is_noise_document,
    select_random_file_hierarchical,
)
from src.utils.json_extraction import extract_json_from_response
from src.utils.json_recovery import JsonRecoveryError, try_recover_json
from src.utils.questions import (
    append_to_jsonl,
    count_existing_questions,
    extract_answer_facts,
    extract_anti_hallucination_facts,
    extract_source_type,
    generate_question,
    get_existing_doc_uuids,
    save_question,
    get_next_question_id,
    load_document,
    validate_question,
)
from src.utils.path_resolver import (
    PathResolver,
    default_resolver,
    normalize_source_path,
    sources_resolver,
    validate_source_path,
)
from src.utils.validation import validate_no_nested_dicts

__all__ = [
    "add_dataset_doc_uuid",
    "collect_json_files_by_size",
    "append_to_jsonl",
    "count_existing_questions",
    "confirm_regenerate",
    "confirm_yes_no",
    "count_json_files",
    "default_resolver",
    "delete_file",
    "dir_has_json_files",
    "is_noise_document",
    "DocumentFieldError",
    "extract_document_content",
    "extract_answer_facts",
    "extract_anti_hallucination_facts",
    "extract_json_from_response",
    "extract_source_type",
    "generate_dataset_doc_uuid",
    "generate_question",
    "DEFAULT_UUID_INDEX_CACHE_FILE",
    "get_existing_doc_uuids",
    "get_agents_md_for_path",
    "get_agents_md_for_source",
    "get_current_date_formatted",
    "get_dataset_doc_uuid",
    "get_directory_tree",
    "get_next_question_id",
    "get_documents_without_labels",
    "JsonRecoveryError",
    "label_document_fields",
    "label_single_document",
    "load_document",
    "load_file",
    "load_file_without_metadata",
    "load_document_content_by_uuid",
    "load_document_json_by_uuid",
    "load_json_file",
    "load_or_build_uuid_index",
    "needs_reordering",
    "normalize_source_path",
    "PathResolver",
    "process_written_document",
    "rebuild_uuid_index",
    "reorder_document_fields",
    "sanitize_filename",
    "sanitize_path",
    "save_question",
    "select_random_file_hierarchical",
    "strip_metadata_fields",
    "sources_resolver",
    "try_recover_json",
    "validate_no_nested_dicts",
    "validate_question",
    "validate_source_path",
    "build_uuid_index",
    "ensure_uuids_resolved",
    "completeness_cache",
    "duplications_cache",
    "GenerationCache",
    "misc_files_cache",
    "projects_cache",
    "unanswerable_used_paths_cache",
    "write_uuid_index_cache",
    "write_json_file",
]
