"""Retrieve documents via Qdrant vector search and generate answers with an LLM.

For each question, embeds the query, retrieves top chunks from a chunked Qdrant
index, deduplicates by document UUID to identify the top-k unique documents,
loads full document content from disk, and generates an answer. Output is
compatible with the existing evaluation harness.

Usage:
    python -m src.scripts.answer_generation.vector_retrieval [OPTIONS]

Args:
    --collection-name   Qdrant collection name (default: "enterpriserag")
    --qdrant-url        Qdrant server URL (default: "http://localhost:6333")
    --top-k             Unique documents to retrieve per question (default: 10)
    --chunk-limit       Max chunks to fetch from Qdrant before deduplication (default: 100)
    --questions-file    Path to questions JSONL (default: QUESTIONS_PATH)
    --output            Output JSONL path (default: "answer_evaluation/answers_vector.jsonl")
    --parallelism       Parallel workers (default: 1)
    --resume            Skip questions already in output file
    --limit             Max questions to process
    --quiet             Suppress LLM output streaming
"""

from __future__ import annotations

import argparse
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
from src.utils.document_index import load_or_build_uuid_index
from src.utils.retrieval import (
    append_result,
    format_context_documents,
    load_existing_question_ids,
    load_questions,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "text-embedding-3-large"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vector retrieval + LLM answer generation."
    )
    parser.add_argument(
        "--collection-name", default="enterpriserag", help="Qdrant collection name"
    )
    parser.add_argument(
        "--qdrant-url", default="http://localhost:6333", help="Qdrant server URL"
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Unique documents to retrieve per question",
    )
    parser.add_argument(
        "--chunk-limit",
        type=int,
        default=100,
        help="Max chunks to fetch from Qdrant before deduplication (default: 100)",
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

        # Search Qdrant for chunks
        results = qdrant.query_points(
            collection_name=args.collection_name,
            query=query_vector,
            limit=args.chunk_limit,
            with_payload=True,
        )

        # Deduplicate chunks to unique documents, preserving rank order
        seen: set[str] = set()
        doc_uuids: list[str] = []
        for point in results.points:
            uid = point.payload.get("dataset_doc_uuid")  # type: ignore[union-attr]
            if uid and uid not in seen:
                seen.add(uid)
                doc_uuids.append(uid)
            if len(doc_uuids) >= args.top_k:
                break

        # Verify we got the expected number of unique documents
        if len(doc_uuids) < args.top_k:
            raise RuntimeError(
                f"Question {qid}: expected {args.top_k} unique documents but "
                f"got {len(doc_uuids)} from {len(results.points)} chunks"
            )

        # Load full documents from disk and format context
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
