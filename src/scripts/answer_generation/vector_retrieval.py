"""Retrieve documents via Qdrant vector search and generate answers with an LLM.

For each question, embeds the query, retrieves top-k documents from Qdrant,
loads full document content, and generates an answer. Output is compatible with
the existing evaluation harness (metrics_based_eval.py, comparative_eval.py).

Usage:
    python -m src.scripts.answer_generation.vector_retrieval [OPTIONS]

Args:
    --collection-name   Qdrant collection name (default: "industryrag")
    --qdrant-url        Qdrant server URL (default: "http://localhost:6333")
    --top-k             Documents to retrieve per question (default: 10)
    --questions-file    Path to questions JSONL (default: QUESTIONS_PATH)
    --output            Output JSONL path (default: "answer_evaluation/answers_vector.jsonl")
    --parallelism       Parallel workers (default: 1)
    --resume            Skip questions already in output file
    --limit             Max questions to process
    --quiet             Suppress LLM output streaming
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from openai import OpenAI
from qdrant_client import QdrantClient
from tqdm import tqdm

from src.llm.factory import get_llm
from src.llm.interface import Message
from src.paths import QUESTIONS_PATH
from src.prompts.vector_search_answer_gen import ANSWER_GEN_PROMPT
from src.utils.document_index import (
    load_document_content_by_uuid,
    load_or_build_uuid_index,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "text-embedding-3-large"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vector retrieval + LLM answer generation."
    )
    parser.add_argument(
        "--collection-name", default="industryrag", help="Qdrant collection name"
    )
    parser.add_argument(
        "--qdrant-url", default="http://localhost:6333", help="Qdrant server URL"
    )
    parser.add_argument(
        "--top-k", type=int, default=10, help="Documents to retrieve per question"
    )
    parser.add_argument(
        "--questions-file", default=QUESTIONS_PATH, help="Path to questions JSONL"
    )
    parser.add_argument(
        "--output",
        default="answer_evaluation/answers_vector.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument("--parallelism", type=int, default=1, help="Parallel workers")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip questions already in output file",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max questions to process"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    # --- Load questions ---
    questions = load_questions(args.questions_file)
    print(f"Loaded {len(questions)} questions from {args.questions_file}")

    # --- Resume ---
    if args.resume:
        existing_ids = load_existing_question_ids(args.output)
        questions = [q for q in questions if q["question_id"] not in existing_ids]
        print(f"  {len(existing_ids)} already answered, {len(questions)} remaining")

    # --- Limit ---
    if args.limit is not None:
        questions = questions[: args.limit]
        print(f"  Processing {len(questions)} questions (--limit {args.limit})")

    if not questions:
        print("Nothing to process.")
        return

    # --- Ensure output directory exists ---
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # --- Init clients ---
    openai_client = OpenAI(api_key=os.environ.get("LLM_API_KEY"))
    qdrant = QdrantClient(url=args.qdrant_url)

    # --- Load UUID index ---
    uuid_index = load_or_build_uuid_index()

    # --- Quiet mode for parallel ---
    use_quiet = args.quiet or args.parallelism > 1

    write_lock = threading.Lock()

    def process_question(question: dict[str, Any]) -> str:
        """Process a single question: embed, retrieve, generate answer."""
        qid: str = question["question_id"]
        query = question["question"]

        # Embed query
        embed_response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL, input=[query]
        )
        query_vector = embed_response.data[0].embedding

        # Search Qdrant
        results = qdrant.query_points(
            collection_name=args.collection_name,
            query=query_vector,
            limit=args.top_k,
            with_payload=True,
        )

        # Extract UUIDs from results
        doc_uuids: list[str] = []
        for point in results.points:
            uuid = point.payload.get("dataset_doc_uuid")  # type: ignore[union-attr]
            if uuid:
                doc_uuids.append(uuid)

        # Format context
        context = format_context_documents(doc_uuids, uuid_index)

        # Generate answer
        prompt = ANSWER_GEN_PROMPT.format(
            context_documents=context,
            question=query,
        )
        llm = get_llm(tools=None, quiet=use_quiet)
        messages = [Message(role="user", content=prompt)]

        response_parts: list[str] = []
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                response_parts.append(chunk)

        answer = "".join(response_parts).strip()

        # Write result
        result = {
            "question_id": qid,
            "answer": answer,
            "document_ids": doc_uuids,
        }
        append_result(args.output, result, write_lock)
        return qid

    # --- Process questions ---
    print(f"Processing {len(questions)} questions ({args.parallelism} workers)...")
    with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
        futures = {
            executor.submit(process_question, q): q["question_id"] for q in questions
        }
        with tqdm(total=len(questions), desc="Questions") as pbar:
            for future in as_completed(futures):
                qid = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"\n  Question {qid} failed: {e}")
                pbar.update(1)

    print(f"\nDone. Results written to {args.output}")


if __name__ == "__main__":
    main()
