"""Utility for extracting content from labeled documents."""


class DocumentFieldError(Exception):
    """Raised when document field labels are missing or invalid."""

    pass


def extract_document_content(doc_data: dict) -> tuple[str, str]:
    """
    Extract title and content from a document using field labels.

    Expects the document to have:
    - title_field_name: Name of the field containing the title
    - content_field_names: List of field names containing the content

    Args:
        doc_data: Parsed JSON document data.

    Returns:
        (title, content) tuple.

    Raises:
        DocumentFieldError: If field labels are missing or invalid.
    """
    # Validate title_field_name exists
    if "title_field_name" not in doc_data:
        raise DocumentFieldError("Document missing 'title_field_name' field")

    title_field_name = doc_data["title_field_name"]
    if title_field_name not in doc_data:
        raise DocumentFieldError(
            f"title_field_name '{title_field_name}' not found in document"
        )

    title = str(doc_data[title_field_name])

    # Validate content_field_names exists
    if "content_field_names" not in doc_data:
        raise DocumentFieldError("Document missing 'content_field_names' field")

    content_field_names = doc_data["content_field_names"]
    if not isinstance(content_field_names, list):
        raise DocumentFieldError("'content_field_names' must be a list")

    if not content_field_names:
        raise DocumentFieldError("'content_field_names' is empty")

    # Validate all content field names exist in document
    for field_name in content_field_names:
        if field_name not in doc_data:
            raise DocumentFieldError(
                f"content_field_name '{field_name}' not found in document"
            )

    # Build content string
    if len(content_field_names) == 1:
        # Single content field - just use the value
        content = str(doc_data[content_field_names[0]])
    else:
        # Multiple content fields - include keys as headers
        content_parts = []
        for field_name in content_field_names:
            value = doc_data[field_name]
            # Handle list values
            if isinstance(value, list):
                value = "\n".join(str(v) for v in value)
            content_parts.append(f"{field_name}:\n{value}")
        content = "\n\n".join(content_parts)

    return (title, content)
