"""Shared utilities for retrieval-based answer generation scripts."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from src.utils.document_index import load_document_content_by_uuid


def load_questions(path: str) -> list[dict[str, Any]]:
    """Load questions from a JSONL file."""
    questions: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            questions.append(json.loads(line))
    return questions


def load_existing_question_ids(path: str) -> set[str]:
    """Load question IDs already present in the output file."""
    ids: set[str] = set()
    if not os.path.exists(path):
        return ids
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                ids.add(data["question_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def append_result(path: str, result: dict[str, Any], lock: threading.Lock) -> None:
    """Append a single result to the output JSONL file (thread-safe)."""
    line = json.dumps(result, ensure_ascii=False)
    with lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def format_context_documents(
    doc_uuids: list[str],
    uuid_index: dict[str, str],
) -> str:
    """Load and format retrieved documents into a context string."""
    parts: list[str] = []
    for i, uuid in enumerate(doc_uuids, 1):
        try:
            title, content = load_document_content_by_uuid(uuid, uuid_index)
            parts.append(
                f"--- Document {i} (ID: {uuid}) ---\n" f"Title: {title}\n\n{content}"
            )
        except Exception as e:
            parts.append(
                f"--- Document {i} (ID: {uuid}) ---\n" f"[Error loading document: {e}]"
            )
    return "\n\n".join(parts)
