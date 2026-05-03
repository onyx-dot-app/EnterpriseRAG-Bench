"""Evaluate a single system's answers against the gold questions dataset.

Scores each answer for correctness, completeness (fact validation percentage), document
recall, and invalid extra documents. Applies the three-judge document correction flow to
update gold sets when candidate documents differ, and regenerates gold answers and facts
when the document set changes.

Usage:
    python -m src.scripts.answer_evaluation.metrics_based_eval [OPTIONS]

Args:
    --answers-file            Path to answers JSONL file (default: answer_evaluation/answers.jsonl)
    --questions-file          Path to questions JSONL file (default: questions.jsonl)
    --results-file            Path to output results JSON (default: answer_evaluation/results.json)
    --updated-questions-file  Path to output updated questions JSONL (default: answer_evaluation/questions_updated.jsonl)
    --uuid-index-cache-file   Path to UUID index cache JSON
    --parallelism             Number of parallel evaluation threads (default: 1)
    --question-id             Evaluate a single question_id only
    --skip-citation-stripping Skip LLM-based citation stripping from answers
    --no-correction       Skip the consensus document-correction flow; score purely
                          against the original gold doc set without rewriting gold
                          answers, facts, or expected_doc_ids.
    --resume              Skip questions already in results file
    --limit               Max questions to process
"""

import argparse
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.utils.eval_utils import (
    DEFAULT_QUESTIONS_FILE,
    build_type_order,
    dedupe_doc_ids,
    evaluate_documents_with_consensus,
    group_results_by_type,
    load_answers,
    load_questions,
    load_updated_questions,
    question_sort_key,
    resolve_document_path_map,
    sort_question_results,
    strip_answer_citations,
    update_gold_answer,
    validate_single_fact,
)
from src.llm import Message, get_llm
from src.prompts.answer_evaluation import ANSWER_WHOLISTIC_EVALUATION_PROMPT
from src.utils.document_index import DEFAULT_UUID_INDEX_CACHE_FILE
from src.utils.file_io import load_json_file, write_json_file
from src.utils.json_extraction import extract_json_from_response
from src.utils.questions import (
    extract_answer_facts,
    extract_anti_hallucination_facts,
    extract_source_type,
)

_MAX_LLM_RETRIES = 3

DEFAULT_ANSWERS_FILE = "answer_evaluation/answers.jsonl"
DEFAULT_OUTPUT_FILE = "answer_evaluation/questions_updated.jsonl"
DEFAULT_RESULTS_FILE = "answer_evaluation/results.json"


# =============================================================================
# LLM Evaluation (metrics-eval specific)
# =============================================================================


def evaluate_answer_correctness(
    question: str,
    gold_answer: str,
    candidate_answer: str,
) -> tuple[bool | None, str]:
    """Evaluate whether the candidate answer is aligned with the gold answer.

    Uses a wholistic LLM evaluation rather than requiring all individual facts
    to match. Returns (is_aligned, reason). is_aligned is None on failure.
    """
    prompt = ANSWER_WHOLISTIC_EVALUATION_PROMPT.format(
        query=question,
        gold_answer=gold_answer,
        candidate_answer=candidate_answer,
    )

    for attempt in range(_MAX_LLM_RETRIES):
        try:
            llm = get_llm(tools=None, quiet=True)
            messages: list[Message] = [Message(role="user", content=prompt)]

            response = ""
            for chunk in llm.generate(messages):
                if isinstance(chunk, str):
                    response += chunk
        except Exception:
            continue

        response = response.strip()

        try:
            parsed = json.loads(extract_json_from_response(response))
        except Exception:
            continue

        if not isinstance(parsed, dict):
            continue

        aligned = parsed.get("aligned", "")
        reason = parsed.get("reason", "")
        if not isinstance(aligned, str):
            continue

        is_aligned = re.search(r"\byes\b", aligned, re.IGNORECASE) is not None
        return (is_aligned, reason if isinstance(reason, str) else "")

    return (None, "")


# =============================================================================
# Per-Question Processing
# =============================================================================


def process_question_docs(
    answer_row: dict,
    questions: dict[str, dict],
    document_path_map: dict[str, str],
) -> tuple[str, dict | None]:
    """Process document evaluation for a single answer row.

    Returns (status_message, updated_question_or_None).
    """
    qid = answer_row.get("question_id")
    if not qid:
        return ("SKIP: missing question_id", None)

    if qid not in questions:
        return (f"SKIP {qid}: question_id not found in questions file", None)

    question_row = questions[qid]
    answer_doc_ids: list[str] = answer_row.get("document_ids") or []
    gold_doc_ids: list[str] = question_row.get("expected_doc_ids", [])

    deduped_doc_ids = dedupe_doc_ids(answer_doc_ids)

    gold_set = set(gold_doc_ids)
    answer_set = set(deduped_doc_ids)

    # If the document sets are identical, no evaluation needed
    if gold_set == answer_set:
        return (f"OK {qid}: document set matches gold", None)

    # Find candidate docs that are not in the gold set, capped at 20
    candidate_only = [d for d in deduped_doc_ids if d not in gold_set]
    if len(candidate_only) > 20:
        candidate_only = random.sample(candidate_only, 20)

    # Evaluate all documents (gold + candidates) with 3-run consensus
    eval_result, gold_confirmed, eval_error = evaluate_documents_with_consensus(
        question=question_row["question"],
        gold_doc_ids=gold_doc_ids,
        candidate_doc_ids=candidate_only,
        document_path_map=document_path_map,
    )

    if eval_result is None:
        return (
            f"[WARN] document evaluation returned unusable output ({eval_error}); "
            "using original gold set",
            None,
        )

    if gold_confirmed:
        return (f"OK {qid}: gold documents confirmed by consensus", None)

    # Build update_reasons from eval_result
    update_reasons: dict[str, dict[str, str]] = {}
    for dsid, info in eval_result.items():
        classification = info.get("classification", "unknown")
        reason = info.get("reason", "")
        update_reasons[dsid] = {
            "classification": classification,
            "reason": reason,
        }

    # Determine the new required document set (only "required" docs)
    required_doc_ids: list[str] = []
    valid_doc_ids: list[str] = []
    for dsid in gold_doc_ids:
        entry = update_reasons.get(dsid, {})
        cls = entry.get("classification", "required")
        if cls == "required":
            required_doc_ids.append(dsid)
        elif cls == "valid":
            valid_doc_ids.append(dsid)

    for dsid in candidate_only:
        entry = update_reasons.get(dsid, {})
        cls = entry.get("classification", "invalid")
        if cls == "required":
            required_doc_ids.append(dsid)
        elif cls == "valid":
            valid_doc_ids.append(dsid)

    if not required_doc_ids:
        return (
            "[WARN] document evaluation marked no documents as required; "
            "using original gold set",
            None,
        )

    new_set = set(required_doc_ids)
    docs_changed = new_set != gold_set

    # Build updated question row
    updated_row = dict(question_row)
    updated_row["updated"] = True
    updated_row["update_reasons"] = update_reasons

    # Store valid (but not required) doc IDs for scoring context
    if valid_doc_ids:
        updated_row["valid_doc_ids"] = valid_doc_ids

    if docs_changed:
        # Regenerate gold answer with updated document set
        new_answer = update_gold_answer(
            question=question_row["question"],
            previous_gold_answer=question_row.get("gold_answer", ""),
            valid_doc_ids=required_doc_ids,
            document_path_map=document_path_map,
        )
        updated_row["expected_doc_ids"] = required_doc_ids
        updated_row["source_types"] = sorted(
            set(
                extract_source_type(document_path_map[doc_id])
                for doc_id in required_doc_ids
                if doc_id in document_path_map
            )
        )

        if not new_answer:
            print(
                f"  [WARN] {qid}: gold answer regeneration failed after doc set "
                "change. Falling back to original gold answer."
            )
            return (
                f"UPDATED {qid}: document set changed ({len(gold_doc_ids)} -> {len(required_doc_ids)} docs) "
                "(gold answer unchanged — regeneration failed)",
                updated_row,
            )

        updated_row["gold_answer"] = new_answer

        # Re-extract facts for the updated gold answer
        original_facts = question_row.get("answer_facts", [])

        # Preserve anti-hallucination guard facts from the original set
        anti_hallucination_facts = (
            extract_anti_hallucination_facts(
                original_facts,
                quiet=True,
            )
            or []
        )

        # Extract new facts from the updated gold answer
        new_facts = (
            extract_answer_facts(
                question_row["question"],
                new_answer,
                quiet=True,
            )
            or []
        )

        # Combine: new facts + anti-hallucination guards (deduped)
        new_facts_set = set(new_facts)
        combined_facts = list(new_facts)
        for fact in anti_hallucination_facts:
            if fact not in new_facts_set:
                combined_facts.append(fact)

        updated_row["answer_facts"] = combined_facts

        return (
            f"UPDATED {qid}: document set changed ({len(gold_doc_ids)} -> {len(required_doc_ids)} docs)",
            updated_row,
        )
    else:
        return (
            f"EVALUATED {qid}: document set unchanged after evaluation",
            None,
        )


def score_answer(
    answer_row: dict,
    question_data: dict,
    original_question_data: dict,
) -> dict:
    """Score a single answer against its question data.

    Returns a dict with per-question metrics.
    """
    qid = answer_row["question_id"]
    answer_text = answer_row.get("answer")
    answer_doc_ids = answer_row.get("document_ids") or []
    expected_doc_ids = question_data.get("expected_doc_ids") or []
    answer_facts = question_data.get("answer_facts", [])
    question_type = original_question_data.get("question_type")
    gold_answer_updated = original_question_data.get(
        "gold_answer"
    ) != question_data.get("gold_answer")
    docs_updated = set(original_question_data.get("expected_doc_ids", [])) != set(
        question_data.get("expected_doc_ids", [])
    )
    question_corrected = gold_answer_updated or docs_updated

    deduped_doc_ids = dedupe_doc_ids(answer_doc_ids)

    expected_set = set(expected_doc_ids)
    answer_doc_set = set(deduped_doc_ids)

    # valid_doc_ids are docs classified as "valid" (relevant but not required)
    valid_doc_id_set = set(question_data.get("valid_doc_ids", []))

    # Document recall and extra docs — N/A when no expected docs
    if expected_set:
        correct_docs = answer_doc_set & expected_set
        document_recall_pct: float | None = len(correct_docs) / len(expected_set) * 100
        non_required = answer_doc_set - expected_set
        invalid_extra_docs: int | None = len(non_required - valid_doc_id_set)
    else:
        document_recall_pct = None
        invalid_extra_docs = None

    # Answer completeness (fact-level) and correctness (wholistic) in parallel
    gold_answer = question_data.get("gold_answer", "")
    question_text = question_data.get(
        "question", original_question_data.get("question", "")
    )

    completeness_pct = 0.0
    answer_correct = False
    correctness_reasoning = ""

    if answer_text:
        # Submit all LLM calls into one pool: individual facts + wholistic eval
        max_workers = max(len(answer_facts), 1) + (1 if gold_answer else 0)
        correctness_future = None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            fact_futures = [
                executor.submit(validate_single_fact, answer_text, statement)
                for statement in answer_facts
            ]

            if gold_answer:
                correctness_future = executor.submit(
                    evaluate_answer_correctness,
                    question_text,
                    gold_answer,
                    answer_text,
                )

            # Collect fact results
            if answer_facts:
                validated_count = 0
                fact_failed = False
                for future in as_completed(fact_futures):
                    try:
                        if future.result():
                            validated_count += 1
                    except Exception:
                        fact_failed = True

                if not fact_failed:
                    validated_count = min(validated_count, len(answer_facts))
                    completeness_pct = validated_count / len(answer_facts) * 100
            else:
                completeness_pct = 100.0

            # Collect correctness result
            if correctness_future is not None:
                try:
                    correctness_result, correctness_reasoning = (
                        correctness_future.result()
                    )
                    answer_correct = (
                        correctness_result if correctness_result is not None else False
                    )
                except Exception:
                    answer_correct = False
            else:
                answer_correct = True

    return {
        "question_id": qid,
        "corrected": question_corrected,
        "question_type": question_type,
        "answer_correct": answer_correct,
        "correctness_reasoning": correctness_reasoning,
        "completeness_pct": round(completeness_pct, 2),
        "document_recall_pct": (
            round(document_recall_pct, 2) if document_recall_pct is not None else None
        ),
        "invalid_extra_docs": invalid_extra_docs,
    }


# =============================================================================
# Statistics & Output
# =============================================================================


def compute_stats_for_group(results: list[dict]) -> dict[str, float | int]:
    """Compute average stats for a group of question results.

    Recall and extra_docs are only averaged over questions that have
    expected documents (non-None values). Questions without expected docs
    are excluded from those averages.
    """
    n = len(results)
    if n == 0:
        return {
            "count": 0,
            "average_correctness_pct": 0.0,
            "average_completeness_pct": 0.0,
            "combined_correctness_completeness_score": 0.0,
            "average_recall_pct": 0.0,
            "average_invalid_extra_docs": 0.0,
        }

    recall_values = [
        r["document_recall_pct"]
        for r in results
        if r["document_recall_pct"] is not None
    ]
    invalid_extra_values = [
        r["invalid_extra_docs"] for r in results if r["invalid_extra_docs"] is not None
    ]

    return {
        "count": n,
        "average_correctness_pct": round(
            sum(1 for r in results if r["answer_correct"]) / n * 100,
            2,
        ),
        "average_completeness_pct": round(
            sum(r["completeness_pct"] for r in results) / n,
            2,
        ),
        "combined_correctness_completeness_score": round(
            sum(r["completeness_pct"] if r["answer_correct"] else 0.0 for r in results)
            / n,
            2,
        ),
        "average_recall_pct": (
            round(
                sum(recall_values) / len(recall_values),
                2,
            )
            if recall_values
            else 0.0
        ),
        "average_invalid_extra_docs": (
            round(
                sum(invalid_extra_values) / len(invalid_extra_values),
                2,
            )
            if invalid_extra_values
            else 0.0
        ),
    }


def build_question_type_stats(
    question_results: list[dict],
    type_order: list[str] | None = None,
) -> dict[str, dict[str, float | int]]:
    """Build per-question-type stats breakdown."""
    grouped = group_results_by_type(question_results, type_order)
    return {qt: compute_stats_for_group(group) for qt, group in grouped.items()}


def build_aggregate_stats(
    question_results: list[dict],
    skip_count: int | str,
    total_questions: int,
) -> dict[str, float | int | str]:
    """Build aggregate stats for the current evaluation snapshot."""
    stats = compute_stats_for_group(question_results)
    num_corrected = sum(1 for r in question_results if r.get("corrected"))
    return {
        "total_questions": total_questions,
        "completed_questions": stats.pop("count"),
        "skipped_rows": skip_count,
        "num_corrected_questions": num_corrected,
        **stats,
    }


def write_results_snapshot(
    results_file: str,
    output_file: str | None,
    question_results: list[dict],
    skip_count: int | str,
    total_questions: int,
    type_order: list[str] | None = None,
) -> None:
    """Write the current results snapshot to disk atomically."""
    sorted_question_results = sort_question_results(question_results)
    results_output: dict = {}
    if output_file is not None:
        results_output["updated_question_file"] = output_file
    results_output["aggregate_stats"] = build_aggregate_stats(
        question_results=question_results,
        skip_count=skip_count,
        total_questions=total_questions,
    )
    results_output["question_type_stats"] = build_question_type_stats(
        question_results, type_order=type_order
    )
    results_output["questions"] = sorted_question_results
    write_json_file(results_file, results_output)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate answer files against gold questions"
    )
    parser.add_argument(
        "--answers-file",
        default=DEFAULT_ANSWERS_FILE,
        help=f"Path to answers JSONL file (default: {DEFAULT_ANSWERS_FILE})",
    )
    parser.add_argument(
        "--questions-file",
        default=DEFAULT_QUESTIONS_FILE,
        help=f"Path to questions JSONL file (default: {DEFAULT_QUESTIONS_FILE})",
    )
    parser.add_argument(
        "--updated-questions-file",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Path to output updated questions JSONL (default: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--results-file",
        default=DEFAULT_RESULTS_FILE,
        help=f"Path to output results JSON (default: {DEFAULT_RESULTS_FILE})",
    )
    parser.add_argument(
        "--uuid-index-cache-file",
        default=DEFAULT_UUID_INDEX_CACHE_FILE,
        help=(
            "Path to the UUID index cache JSON file "
            f"(default: {DEFAULT_UUID_INDEX_CACHE_FILE})"
        ),
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="Number of parallel evaluation threads (default: 1)",
    )
    parser.add_argument(
        "--question-id",
        help=(
            "Only evaluate a single question_id. Forces parallelism=1 and "
            "reruns that question even if it already exists in the results file."
        ),
    )
    parser.add_argument(
        "--skip-citation-stripping",
        action="store_true",
        default=False,
        help="Skip LLM-based citation stripping from answers",
    )
    parser.add_argument(
        "--no-correction",
        action="store_true",
        default=False,
        help=(
            "Skip the consensus document-correction flow; score purely against "
            "the original gold doc set. No gold answer/fact regeneration, no "
            "questions_updated.jsonl is written."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip questions already in results file",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max questions to process"
    )
    args = parser.parse_args()

    # Validate input files exist
    if not os.path.exists(args.answers_file):
        print(f"Error: answer file not found: {args.answers_file}")
        sys.exit(1)
    if not os.path.exists(args.questions_file):
        print(f"Error: questions file not found: {args.questions_file}")
        sys.exit(1)

    if args.question_id and args.parallelism != 1:
        print("  [INFO] --question-id set; forcing parallelism=1")
        args.parallelism = 1

    # Resume vs overwrite decision is deferred until we know how many
    # questions are missing (see section 2 below).

    # =========================================================================
    # 1. Load questions and answers
    # =========================================================================

    print(f"Loading questions from {args.questions_file}...")
    questions = load_questions(args.questions_file)
    print(f"  Loaded {len(questions)} questions")

    type_order = build_type_order(questions)

    print(f"Loading answers from {args.answers_file}...")
    answers = load_answers(args.answers_file)
    print(f"  Loaded {len(answers)} answer rows")

    # Validate answer rows and separate failures
    valid_rows: list[dict] = []
    skip_count = 0
    for row in answers:
        qid = row.get("question_id")
        if not qid:
            print(f"  [FAIL] Row missing question_id: {json.dumps(row)[:120]}...")
            skip_count += 1
        elif qid not in questions:
            print(f"  [FAIL] question_id '{qid}' not found in questions file")
            skip_count += 1
        elif not row.get("document_ids") and not row.get("answer"):
            print(f"  [FAIL] {qid}: row has neither answer nor document_ids")
            skip_count += 1
        else:
            valid_rows.append(row)

    if skip_count:
        print(f"\n  {skip_count} rows skipped due to failures")

    if args.question_id:
        selected_rows = [
            row for row in valid_rows if row["question_id"] == args.question_id
        ]
        if not selected_rows:
            print(
                f"Error: question_id '{args.question_id}' not found in the "
                "validated answer rows"
            )
            sys.exit(1)
        if len(selected_rows) > 1:
            print(
                f"Error: question_id '{args.question_id}' appeared "
                f"{len(selected_rows)} times in the validated answer rows"
            )
            sys.exit(1)

        valid_rows = selected_rows
        print(f"  Targeting single question: {args.question_id}")

    # =========================================================================
    # 2. Compare with existing results to find new questions
    # =========================================================================

    question_results: list[dict] = []
    completed_qids: set[str] = set()

    if args.question_id:
        # Single-question mode: keep other results, re-evaluate target
        if os.path.exists(args.results_file):
            try:
                existing_results = load_json_file(args.results_file)
                for r in existing_results.get("questions", []):
                    qid = r.get("question_id")
                    question_results.append(r)
                    if qid and qid != args.question_id:
                        completed_qids.add(qid)
            except Exception:
                print(
                    f"  [WARN] Could not load existing results from "
                    f"{args.results_file}, starting fresh"
                )
    elif args.resume and os.path.exists(args.results_file):
        try:
            existing_results = load_json_file(args.results_file)
            for r in existing_results.get("questions", []):
                qid = r.get("question_id")
                question_results.append(r)
                if qid:
                    completed_qids.add(qid)
        except Exception:
            print(
                f"  [WARN] Could not load existing results from "
                f"{args.results_file}, starting fresh"
            )

    answer_qids = {row["question_id"] for row in valid_rows}
    new_qids = answer_qids - completed_qids
    is_resuming = False

    if completed_qids and not args.question_id:
        overlapping_qids = answer_qids & completed_qids
        print(
            f"\n  Found {len(completed_qids)} already-evaluated questions "
            f"in {args.results_file}"
        )
        print(f"  {len(overlapping_qids)} overlapping with current answer set")
        print(f"  {len(new_qids)} new questions to evaluate")

        if new_qids:
            print(f"\n  Resuming evaluation for {len(new_qids)} missing questions...")
            is_resuming = True
        else:
            print("\n  All questions already evaluated, nothing to do.")
            sys.exit(0)
    else:
        print(f"\n  {len(answer_qids)} questions to evaluate")

    # =========================================================================
    # 3. Build and validate UUID path map
    # =========================================================================

    updated_questions: dict[str, dict] = {}
    document_path_map: dict[str, str] = {}

    if args.no_correction:
        print(
            "  --no-correction set; skipping updated-questions load and "
            "document path resolution"
        )
    else:
        updated_questions = load_updated_questions(args.updated_questions_file)
        if updated_questions:
            print(
                f"  Loaded {len(updated_questions)} updated questions from "
                f"{args.updated_questions_file}"
            )
        if args.question_id:
            updated_questions.pop(args.question_id, None)

        try:
            document_path_map = resolve_document_path_map(
                questions=questions,
                answer_sets=[answers],
                updated_questions=updated_questions,
                uuid_index_cache_file=args.uuid_index_cache_file,
            )
        except ValueError as exc:
            print(f"\nFATAL: {exc}")
            sys.exit(1)

    # =========================================================================
    # 4. Prepare worker pool and incremental output state
    # =========================================================================

    remaining_rows = [
        row for row in valid_rows if row["question_id"] not in completed_qids
    ]
    if args.limit is not None:
        remaining_rows = remaining_rows[: args.limit]
        print(f"  Processing {len(remaining_rows)} questions (--limit {args.limit})")

    if args.question_id:
        total_questions = len(question_results) + len(valid_rows)
    else:
        total_questions = len(valid_rows)

    # When resuming, the original skip_count is not recoverable
    display_skip_count: int | str = "N/A" if is_resuming else skip_count
    results_output_file: str | None = (
        None if args.no_correction else args.updated_questions_file
    )

    # Initialize results file
    write_results_snapshot(
        results_file=args.results_file,
        output_file=results_output_file,
        question_results=question_results,
        skip_count=display_skip_count,
        total_questions=total_questions,
        type_order=type_order,
    )

    def evaluate_single_question(
        row: dict,
    ) -> tuple[dict | None, dict]:
        """Evaluate a single question: strip citations, doc eval, scoring."""
        qid = row["question_id"]

        # Strip citations per-question
        if row.get("answer") and not args.skip_citation_stripping:
            try:
                row["answer"] = strip_answer_citations(row["answer"])
            except Exception:
                print(f"  [WARN] {qid}: citation stripping failed, using original")

        updated_q: dict | None = None
        has_expected_docs = bool(questions[qid].get("expected_doc_ids"))

        if not args.no_correction and row.get("document_ids") and has_expected_docs:
            status, updated_q = process_question_docs(
                row,
                questions,
                document_path_map,
            )
            print(f"  {qid} docs: {status}")

        original_question = questions[qid]
        effective_question = updated_q if updated_q else original_question
        result = score_answer(row, effective_question, original_question)
        recall_str = (
            f"{result['document_recall_pct']}%"
            if result["document_recall_pct"] is not None
            else "N/A"
        )
        extra_str = (
            str(result["invalid_extra_docs"])
            if result["invalid_extra_docs"] is not None
            else "N/A"
        )
        print(
            f"  {qid} score: correct={result['answer_correct']}"
            f"  completeness={result['completeness_pct']}%"
            f"  recall={recall_str}"
            f"  extra_docs={extra_str}"
        )
        return updated_q, result

    def handle_completed_question(
        updated_q: dict | None,
        result: dict,
    ) -> None:
        """Record a completed question and flush results to disk."""
        qid = result["question_id"]
        # Only store entries that represent actual corrections. Stale entries
        # from previous runs are safe: on resume skipped questions keep their
        # prior entries, and on a full re-run every question is re-evaluated
        # so each entry is either overwritten here or left absent.
        if updated_q:
            updated_questions[qid] = updated_q

        question_results[:] = [
            existing
            for existing in question_results
            if existing.get("question_id") != qid
        ]
        question_results.append(result)

        write_results_snapshot(
            results_file=args.results_file,
            output_file=results_output_file,
            question_results=question_results,
            skip_count=display_skip_count,
            total_questions=total_questions,
            type_order=type_order,
        )

    # =========================================================================
    # 5. Run evaluation
    # =========================================================================

    remaining_count = len(remaining_rows)
    if remaining_count == 0:
        print("\nAll questions already evaluated, nothing to do.")
    else:
        if args.parallelism > 1:
            print(
                f"\nEvaluating {remaining_count} questions with "
                f"{args.parallelism} parallel workers "
            )
        else:
            print(f"\nEvaluating {remaining_count} questions sequentially...")

        if args.parallelism <= 1:
            for i, row in enumerate(remaining_rows, 1):
                print(f"\n[{i}/{remaining_count}] {row['question_id']}")
                updated_q, result = evaluate_single_question(row)
                handle_completed_question(updated_q, result)
        else:
            with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
                futures = {
                    executor.submit(evaluate_single_question, row): row
                    for row in remaining_rows
                }
                # Workers only evaluate; main thread handles all writes
                for future in as_completed(futures):
                    updated_q, result = future.result()
                    handle_completed_question(updated_q, result)

    # =========================================================================
    # 6. Final sort and write both output files in correct question_id order
    # =========================================================================

    print("\nFinalizing output files (sorting and writing results)...")

    # Sort and write results.json
    print(f"  Writing {args.results_file}...")
    write_results_snapshot(
        results_file=args.results_file,
        output_file=results_output_file,
        question_results=question_results,
        skip_count=display_skip_count,
        total_questions=total_questions,
        type_order=type_order,
    )

    if args.no_correction:
        print(
            "  --no-correction set; skipping write of " f"{args.updated_questions_file}"
        )
    else:
        # Build corrected qids from results
        corrected_qids: set[str] = set()
        for r in question_results:
            if r.get("corrected"):
                corrected_qids.add(r["question_id"])

        # Write questions_updated.jsonl from original questions + updates, sorted
        print(f"  Writing {args.updated_questions_file}...")
        all_question_rows: list[dict] = []
        with open(args.questions_file) as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                row = json.loads(stripped)
                qid = row.get("question_id")
                if qid and qid in updated_questions:
                    row = dict(updated_questions[qid])
                if qid and qid in corrected_qids:
                    # Insert "corrected" as second field after question_id
                    ordered: dict = {}
                    for key, value in row.items():
                        if key == "corrected":
                            continue
                        ordered[key] = value
                        if key == "question_id":
                            ordered["corrected"] = True
                    row = ordered
                else:
                    row = {k: v for k, v in row.items() if k != "corrected"}
                all_question_rows.append(row)

        all_question_rows.sort(key=question_sort_key)
        os.makedirs(os.path.dirname(args.updated_questions_file), exist_ok=True)
        with open(args.updated_questions_file, "w") as f:
            for row in all_question_rows:
                f.write(json.dumps(row) + "\n")

    # =========================================================================
    # 7. Print aggregate stats
    # =========================================================================

    aggregate_stats = build_aggregate_stats(
        question_results=question_results,
        skip_count=display_skip_count,
        total_questions=total_questions,
    )

    print("\nDone.")
    print(f"  Questions scored:    {aggregate_stats['completed_questions']}")
    print(f"  Skipped rows:        {display_skip_count}")
    print(f"  Corrected questions: {aggregate_stats['num_corrected_questions']}")
    print(f"  Avg correctness:     {aggregate_stats['average_correctness_pct']}%")
    print(f"  Avg completeness:    {aggregate_stats['average_completeness_pct']}%")
    print(
        f"  Combined corr*comp:  "
        f"{aggregate_stats['combined_correctness_completeness_score']}"
    )
    print(f"  Avg recall:          {aggregate_stats['average_recall_pct']}%")
    print(f"  Avg invalid extra:   {aggregate_stats['average_invalid_extra_docs']}")


if __name__ == "__main__":
    main()
