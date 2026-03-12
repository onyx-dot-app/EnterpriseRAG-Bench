"""Tool for reading document contents with title/content extraction and read tracking."""

import json

from src.tools.tool_implementations.read import ReadTool
from src.utils.document_content import DocumentFieldError, extract_document_content


class DocumentReadTool(ReadTool):
    """ReadTool subclass that extracts document content and tracks reads.

    When generated_doc_contents is True, returns extracted title+content
    instead of raw JSON, and tracks which documents were read.
    """

    def __init__(
        self,
        base_dir: str,
        generated_doc_contents: bool = False,
        display_name: str | None = None,
    ):
        """
        Initialize the DocumentReadTool.

        Args:
            base_dir: Base directory for file reads.
            generated_doc_contents: If True, extract and return title+content
                instead of raw JSON, and track reads.
            display_name: Name to show in schema description.
        """
        super().__init__(base_dir, display_name)
        self._generated_doc_contents = generated_doc_contents
        self._read_documents: list[dict] = []

    @property
    def read_documents(self) -> list[dict]:
        """Documents read so far. Each dict has keys: path, uuid, title, content."""
        return list(self._read_documents)

    def reset(self) -> None:
        """Clear tracked reads for reuse across iterations."""
        self._read_documents.clear()

    def execute(self, path: str) -> str:
        """
        Read a file, optionally extracting document content.

        Args:
            path: Path to the file (relative to base directory).

        Returns:
            Extracted title+content if generated_doc_contents is True,
            otherwise raw file contents. Returns error message on failure.
        """
        raw = super().execute(path)

        if not self._generated_doc_contents or raw.startswith("Error:"):
            return raw

        try:
            doc_data = json.loads(raw)
            title, content = extract_document_content(doc_data)
            uuid = doc_data.get("dataset_doc_uuid", "")

            normalized_path = self._normalize_path(path)
            self._read_documents.append({
                "path": normalized_path,
                "uuid": uuid,
                "title": title,
                "content": content,
            })

            return f"{title}\n{content}"
        except (json.JSONDecodeError, DocumentFieldError):
            return raw
