"""Retrieve documents via OpenSearch BM25 search and generate answers with an LLM.

For each question, runs a BM25 query against OpenSearch, retrieves top-k
documents, loads full document content, and generates an answer. Output is
compatible with the existing evaluation harness (metrics_based_eval.py,
comparative_eval.py).

Usage:
    python -m src.scripts.answer_generation.bm25_retrieval [OPTIONS]

Args:
    --index-name        OpenSearch index name (default: "enterpriserag")
    --opensearch-url    OpenSearch server URL (default: "http://localhost:9200")
    --top-k             Documents to retrieve per question (default: 10)
    --questions-file    Path to questions JSONL (default: QUESTIONS_PATH)
    --output            Output JSONL path (default: "answer_evaluation/answers_bm25.jsonl")
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

from opensearchpy import OpenSearch
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
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BM25 retrieval + LLM answer generation."
    )
    parser.add_argument(
        "--index-name", default="enterpriserag", help="OpenSearch index name"
    )
    parser.add_argument(
        "--opensearch-url",
        default="http://localhost:9200",
        help="OpenSearch server URL",
    )
    parser.add_argument(
        "--top-k", type=int, default=10, help="Documents to retrieve per question"
    )
    parser.add_argument(
        "--questions-file", default=QUESTIONS_PATH, help="Path to questions JSONL"
    )
    parser.add_argument(
        "--output",
        default="answer_evaluation/answers_bm25.jsonl",
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
    client = OpenSearch(
        hosts=[args.opensearch_url],
        use_ssl=False,
        verify_certs=False,
    )

    # --- Load UUID index ---
    uuid_index = load_or_build_uuid_index()

    # --- Quiet mode for parallel ---
    use_quiet = args.quiet or args.parallelism > 1

    write_lock = threading.Lock()

    def process_question(question: dict[str, Any]) -> str:
        """Process a single question: BM25 search, load docs, generate answer."""
        qid: str = question["question_id"]
        query = question["question"]

        # Search OpenSearch with BM25
        body = {
            "query": {
                "match": {
                    "text": {
                        "query": query,
                    }
                }
            },
            "size": args.top_k,
            "_source": ["dataset_doc_uuid"],
        }
        response = client.search(index=args.index_name, body=body)

        # Extract UUIDs from results
        doc_uuids: list[str] = []
        for hit in response["hits"]["hits"]:
            uuid = hit["_source"].get("dataset_doc_uuid")
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
    failed: list[tuple[str, Exception]] = []
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
                    failed.append((qid, e))
                    print(f"\n  Question {qid} failed: {e}")
                pbar.update(1)

    if failed:
        raise RuntimeError(
            f"{len(failed)}/{len(questions)} questions failed: "
            + ", ".join(qid for qid, _ in failed)
        )

    # --- Verify full coverage ---
    answered_ids = load_existing_question_ids(args.output)
    expected_ids = {q["question_id"] for q in load_questions(args.questions_file)}
    missing = expected_ids - answered_ids
    if missing:
        raise RuntimeError(
            f"{len(missing)} questions missing from output: "
            + ", ".join(sorted(missing)[:10])
            + (" ..." if len(missing) > 10 else "")
        )

    print(f"\nDone. All {len(answered_ids)} questions answered in {args.output}")


if __name__ == "__main__":
    main()
