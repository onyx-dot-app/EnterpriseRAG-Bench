"""Utility for labeling document fields (title and content)."""

import json
import os

from src.llm import Message, get_llm
from src.schemas.field_labels import (
    parse_field_labels,
    validate_field_labels,
    validate_field_labels_against_document,
)
from src.utils.field_ordering import (
    needs_reordering,
    reorder_document_fields,
    strip_metadata_fields,
)
from src.utils.file_io import load_json_file, write_json_file
from src.utils.json_extraction import extract_json_from_response

FIELD_LABELER_PROMPT = """
Given the following JSON document, identify the best title and content fields. The title field is always a single key and the content field is typically a single key but may be a list of keys. \
Output the title and content fields as a JSON object with the following format:

JSON document:
```json
{json_document}
```

# Title field guidance:
- Sometimes the title field is already called title or something obvious in which case just point to that field.
- If there is only text, it may be the first sentence of the document. For markdown, it may be the first heading.
- For things like discussion threads, it could be the channel name.
- For things like tickets, it could be the short (not paragraph/long) summary or name of the ticket, and not the UUID. If there is no short title/summary, use the next best thing which would be the UUID.
- For most documents, this should be fairly obvious.

# Content fields guidance:
- Choose the main content field(s) of the document.
- Never include metadata fields.
- For certain types of documents, there may be multiple body like fields that should be included.
- For discussion threads, the content fields may include all the individual messages in the thread.
- For documents, it may start with the main contents of the document followed by comments from other users.
- If in doubt, keep the content field simple and as few items as possible (typically just one).
- Organize the content fields (if more than one) into a logical reading order.

# Output format:
```json
{{
  "title_field_name": "title_field_name",
  "content_field_names": ["content_field_name_1", "content_field_name_2", ...]
}}
```

CRITICAL: Output ONLY the JSON content, no markdown code blocks or explanations. The keys (title_field_name and content_field_names) must be those exact keys and the values must exist as keys in the JSON document.
""".strip()


def label_document_fields(document: dict, quiet: bool = False) -> dict:
    """
    Run field labeling on a document to identify title and content fields.

    Args:
        document: The parsed document JSON.
        quiet: If True, suppress LLM status output.

    Returns:
        Updated document with title_field_name and content_field_names added.

    Raises:
        ValueError: If field labeling fails validation.
    """
    # Strip metadata fields so the LLM only sees actual document content
    clean_document = strip_metadata_fields(document)

    # Build the prompt
    prompt = FIELD_LABELER_PROMPT.format(
        json_document=json.dumps(clean_document, indent=2),
    )

    # Get LLM response (no tools needed)
    llm = get_llm(quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    # Extract and validate JSON
    json_str = extract_json_from_response(response)

    validation_error = validate_field_labels(json_str)
    if validation_error:
        raise ValueError(f"Field labels validation failed: {validation_error}")

    field_labels = parse_field_labels(json_str)

    # Validate that the field names exist in the document
    doc_validation_error = validate_field_labels_against_document(
        field_labels, document
    )
    if doc_validation_error:
        raise ValueError(f"Field labels reference invalid keys: {doc_validation_error}")

    # Add the field labels to the document
    document["title_field_name"] = field_labels.title_field_name
    document["content_field_names"] = field_labels.content_field_names

    return document


def label_single_document(
    file_path: str, quiet: bool = False, fix_ordering: bool = True
) -> tuple[bool, str]:
    """
    Add field labels to a single document file.

    Args:
        file_path: Full path to the document file.
        quiet: If True, suppress LLM status output.
        fix_ordering: If True, reorder fields to ensure correct ordering.

    Returns:
        (success, message) tuple.
    """
    try:
        # Load existing document
        document = load_json_file(file_path)
        needs_write = False
        message = ""

        # Check if already labeled
        if "title_field_name" in document and "content_field_names" in document:
            message = "Skipped (already labeled)"
        else:
            # Run field labeling
            document = label_document_fields(document, quiet=quiet)
            needs_write = True
            message = "Labeled"

        # Check and fix field ordering
        if fix_ordering and needs_reordering(document):
            document = reorder_document_fields(document)
            needs_write = True
            if message == "Skipped (already labeled)":
                message = "Fixed ordering"
            else:
                message += ", fixed ordering"

        if needs_write:
            write_json_file(file_path, document)

        return (True, message)

    except ValueError as e:
        return (False, str(e))
    except Exception as e:
        return (False, f"Error: {e}")


def get_documents_without_labels(directory: str) -> list[str]:
    """
    Return list of document JSON files that don't have field labels.

    Args:
        directory: Directory to search for documents.

    Returns:
        List of full file paths missing field labels.
    """
    missing: list[str] = []
    if not os.path.exists(directory):
        return missing

    for root, _dirs, files in os.walk(directory):
        for filename in files:
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(root, filename)
            try:
                data = load_json_file(filepath)
                # Check if field labels are missing
                if "title_field_name" not in data or "content_field_names" not in data:
                    missing.append(filepath)
            except (json.JSONDecodeError, OSError):
                continue

    return missing
