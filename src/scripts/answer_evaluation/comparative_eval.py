"""Compare two RAG systems' answers head-to-head against gold questions.

Scores two answer files side-by-side, producing per-question preferences via three-judge
consensus voting and per-system metrics (correctness, completeness, document recall,
invalid extra documents). Applies the document correction flow to update gold sets when
candidate documents are judged valid by majority vote.

Usage:
    python -m src.scripts.answer_evaluation.comparative_eval \\
        --answer-file-1 path/to/system1_answers.jsonl \\
        --answer-file-2 path/to/system2_answers.jsonl

Args:
    --answer-file-1           Path to system 1 answers JSONL (required)
    --answer-file-2           Path to system 2 answers JSONL (required)
    --questions-file          Path to questions JSONL file (default: questions.jsonl)
    --results-file            Path to output results JSON (default: answer_evaluation/results-comparative.json)
    --updated-questions-file  Path to output updated questions JSONL (default: answer_evaluation/questions_updated_comparative.jsonl)
    --uuid-index-cache-file   Path to UUID index cache JSON
    --parallelism             Number of parallel evaluation threads (default: 1)
    --question-id             Evaluate a single question_id only
    --skip-citation-stripping Skip LLM-based citation stripping from answers
    --resume              Skip questions already in results file
    --limit               Max questions to process
"""

import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.utils.eval_utils import (
    DEFAULT_QUESTIONS_FILE,
    _MAX_LLM_RETRIES,
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
from src.prompts.comparative_answer_eval import (
    COMPARATIVE_EVAL_PROMPT,
    DOCUMENT_TEMPLATE,
    IS_GOLD_DOCUMENT_STR,
)
from src.utils.document_index import (
    DEFAULT_UUID_INDEX_CACHE_FILE,
    load_document_content_by_uuid,
)
from src.utils.file_io import load_json_file, write_json_file
from src.utils.json_extraction import extract_json_from_response
from src.utils.questions import extract_answer_facts, extract_anti_hallucination_facts

DEFAULT_RESULTS_FILE = "answer_evaluation/results-comparative.json"
DEFAULT_UPDATED_QUESTIONS_FILE = "answer_evaluation/questions_updated_comparative.jsonl"


# =============================================================================
# Document Formatting
# =============================================================================


def format_document_section(
    doc_ids: list[str],
    gold_doc_ids: set[str],
    document_path_map: dict[str, str],
) -> str:
    """Format a list of documents using DOCUMENT_TEMPLATE.

    Gold documents are marked with IS_GOLD_DOCUMENT_STR.
    Returns "(none)" if doc_ids is empty.
    """
    if not doc_ids:
        return "(none)"

    parts: list[str] = []
    for i, dsid in enumerate(doc_ids, 1):
        title, content = load_document_content_by_uuid(dsid, document_path_map)
        is_gold = IS_GOLD_DOCUMENT_STR if dsid in gold_doc_ids else ""
        parts.append(
            DOCUMENT_TEMPLATE.format(
                number=i,
                is_gold_document_str=is_gold,
                document_title=title,
                document_contents=content,
            )
        )
    return "\n".join(parts)


# =============================================================================
# Comparison LLM
# =============================================================================


def compare_answers(
    question: str,
    answer_1: str,
    answer_2: str,
    overlapping_doc_ids: list[str],
    only_1_doc_ids: list[str],
    only_2_doc_ids: list[str],
    gold_doc_ids: set[str],
    document_path_map: dict[str, str],
) -> dict | None:
    """Single LLM comparison of two answers. Returns parsed result or None."""
    overlapping_text = format_document_section(
        overlapping_doc_ids, gold_doc_ids, document_path_map
    )
    system_1_text = format_document_section(
        only_1_doc_ids, gold_doc_ids, document_path_map
    )
    system_2_text = format_document_section(
        only_2_doc_ids, gold_doc_ids, document_path_map
    )
    presented_ids = set(overlapping_doc_ids) | set(only_1_doc_ids) | set(only_2_doc_ids)
    missing_gold_ids = [d for d in gold_doc_ids if d not in presented_ids]
    missing_gold_text = format_document_section(
        missing_gold_ids, gold_doc_ids, document_path_map
    )

    prompt = COMPARATIVE_EVAL_PROMPT.format(
        query=question,
        candidate_answer_1=answer_1,
        candidate_answer_2=answer_2,
        overlapping_documents=overlapping_text,
        retrieved_documents_1=system_1_text,
        retrieved_documents_2=system_2_text,
        missing_gold_documents=missing_gold_text,
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

        preferred = parsed.get("preferred_system", "")
        equivalent = parsed.get("effectively_equivalent", "")
        reason = parsed.get("reason", "")

        if not isinstance(preferred, str) or preferred not in ("1", "2"):
            continue
        if not isinstance(equivalent, str) or equivalent.lower() not in (
            "true",
            "false",
        ):
            continue

        return {
            "preferred_system": preferred,
            "effectively_equivalent": equivalent.lower() == "true",
            "reason": reason if isinstance(reason, str) else "",
        }

    return None


def compare_answers_with_consensus(
    question: str,
    answer_1: str,
    answer_2: str,
    overlapping_doc_ids: list[str],
    only_1_doc_ids: list[str],
    only_2_doc_ids: list[str],
    gold_doc_ids: set[str],
    document_path_map: dict[str, str],
) -> dict | None:
    """Run answer comparison 3 times and return majority-vote result.

    Returns {preferred_system, effectively_equivalent, reason} or None.
    """
    num_runs = 3
    all_results: list[dict] = []

    for run_idx in range(num_runs):
        result = compare_answers(
            question=question,
            answer_1=answer_1,
            answer_2=answer_2,
            overlapping_doc_ids=overlapping_doc_ids,
            only_1_doc_ids=only_1_doc_ids,
            only_2_doc_ids=only_2_doc_ids,
            gold_doc_ids=gold_doc_ids,
            document_path_map=document_path_map,
        )
        if result is None:
            print(f"    [WARN] Comparison run {run_idx + 1}/{num_runs} failed")
            continue
        all_results.append(result)

    if not all_results:
        return None

    # Majority vote on preferred_system
    pref_1_count = sum(1 for r in all_results if r["preferred_system"] == "1")
    pref_2_count = len(all_results) - pref_1_count
    majority_preferred = "1" if pref_1_count >= pref_2_count else "2"

    # Majority vote on effectively_equivalent
    equiv_count = sum(1 for r in all_results if r["effectively_equivalent"])
    majority_equivalent = equiv_count > len(all_results) / 2

    # Use first successful run's reason
    reason = all_results[0]["reason"]

    return {
        "preferred_system": majority_preferred,
        "effectively_equivalent": majority_equivalent,
        "reason": reason,
    }


# =============================================================================
# Per-Answer-Set Scoring
# =============================================================================


def score_answer_set(
    answer_text: str | None,
    answer_doc_ids: list[str],
    expected_doc_ids: list[str],
    answer_facts: list[str],
) -> dict:
    """Score a single answer set (completeness, recall, extra docs)."""
    deduped = dedupe_doc_ids(answer_doc_ids)
    expected_set = set(expected_doc_ids)
    answer_set = set(deduped)

    # Document recall and extra docs
    if expected_set:
        correct_docs = answer_set & expected_set
        document_recall_pct: float | None = len(correct_docs) / len(expected_set) * 100
        invalid_extra_docs: int | None = len(answer_set - expected_set)
    else:
        document_recall_pct = None
        invalid_extra_docs = None

    # Completeness via fact validation
    completeness_pct = 0.0
    if answer_text and answer_facts:
        max_workers = max(len(answer_facts), 1)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(validate_single_fact, answer_text, fact)
                for fact in answer_facts
            ]
            validated_count = 0
            fact_failed = False
            for future in as_completed(futures):
                try:
                    if future.result():
                        validated_count += 1
                except Exception:
                    fact_failed = True

            if not fact_failed:
                validated_count = min(validated_count, len(answer_facts))
                completeness_pct = validated_count / len(answer_facts) * 100
    elif answer_text and not answer_facts:
        completeness_pct = 100.0

    return {
        "completeness_pct": round(completeness_pct, 2),
        "document_recall_pct": (
            round(document_recall_pct, 2) if document_recall_pct is not None else None
        ),
        "invalid_extra_docs": invalid_extra_docs,
    }


# =============================================================================
# Per-Question Processing
# =============================================================================


def process_comparative_question(
    qid: str,
    row_1: dict,
    row_2: dict,
    questions: dict[str, dict],
    document_path_map: dict[str, str],
    skip_citation_stripping: bool,
) -> tuple[dict | None, dict]:
    """Process a single question for comparative evaluation.

    Returns (updated_question_or_None, result_dict).
    """
    question_row = questions[qid]

    # Strip citations
    answer_1 = row_1.get("answer", "") or ""
    answer_2 = row_2.get("answer", "") or ""

    if not skip_citation_stripping:
        if answer_1:
            try:
                answer_1 = strip_answer_citations(answer_1)
            except Exception:
                print(f"  [WARN] {qid}: citation stripping failed for system 1")
        if answer_2:
            try:
                answer_2 = strip_answer_citations(answer_2)
            except Exception:
                print(f"  [WARN] {qid}: citation stripping failed for system 2")

    docs_1 = dedupe_doc_ids(row_1.get("document_ids") or [])
    docs_2 = dedupe_doc_ids(row_2.get("document_ids") or [])

    gold_doc_ids: list[str] = question_row.get("expected_doc_ids", [])
    gold_set = set(gold_doc_ids)
    has_expected_docs = bool(gold_doc_ids)

    # Document evaluation: union of both systems' docs as candidates
    updated_q: dict | None = None

    if has_expected_docs:
        # Cap candidate (non-gold) docs at 10 per system
        cands_1 = [d for d in docs_1 if d not in gold_set]
        cands_2 = [d for d in docs_2 if d not in gold_set]
        if len(cands_1) > 10:
            cands_1 = random.sample(cands_1, 10)
        if len(cands_2) > 10:
            cands_2 = random.sample(cands_2, 10)
        candidate_only = list(dict.fromkeys(cands_1 + cands_2))

        if candidate_only:
            eval_result, gold_confirmed, eval_error = evaluate_documents_with_consensus(
                question=question_row["question"],
                gold_doc_ids=gold_doc_ids,
                candidate_doc_ids=candidate_only,
                document_path_map=document_path_map,
            )

            if eval_result is not None and not gold_confirmed:
                # Build valid doc set from consensus
                update_reasons: dict[str, dict[str, str]] = {}
                for dsid, info in eval_result.items():
                    update_reasons[dsid] = {
                        "classification": info.get("classification", "unknown"),
                        "reason": info.get("reason", ""),
                    }

                valid_doc_ids: list[str] = []
                for dsid in gold_doc_ids:
                    entry = update_reasons.get(dsid, {})
                    if entry.get("classification", "valid") != "invalid":
                        valid_doc_ids.append(dsid)
                for dsid in candidate_only:
                    entry = update_reasons.get(dsid, {})
                    if entry.get("classification") == "valid":
                        valid_doc_ids.append(dsid)

                if valid_doc_ids and set(valid_doc_ids) != gold_set:
                    # Docs changed — regenerate gold answer
                    updated_row = dict(question_row)
                    updated_row["updated"] = True
                    updated_row["update_reasons"] = update_reasons
                    updated_row["expected_doc_ids"] = valid_doc_ids

                    new_answer = update_gold_answer(
                        question=question_row["question"],
                        previous_gold_answer=question_row.get("gold_answer", ""),
                        valid_doc_ids=valid_doc_ids,
                        document_path_map=document_path_map,
                    )

                    if not new_answer:
                        print(
                            f"  [WARN] {qid}: gold answer regeneration failed. "
                            "Falling back to original gold answer."
                        )
                    else:
                        updated_row["gold_answer"] = new_answer

                        # Re-extract facts
                        original_facts = question_row.get("answer_facts", [])
                        anti_hallucination_facts = (
                            extract_anti_hallucination_facts(original_facts, quiet=True)
                            or []
                        )
                        new_facts = (
                            extract_answer_facts(
                                question_row["question"], new_answer, quiet=True
                            )
                            or []
                        )
                        new_facts_set = set(new_facts)
                        combined_facts = list(new_facts)
                        for fact in anti_hallucination_facts:
                            if fact not in new_facts_set:
                                combined_facts.append(fact)
                        updated_row["answer_facts"] = combined_facts

                    updated_q = updated_row
                    print(
                        f"  {qid} docs: UPDATED ({len(gold_doc_ids)} -> "
                        f"{len(valid_doc_ids)} docs)"
                    )
                elif eval_result is not None:
                    print(f"  {qid} docs: evaluated, doc set unchanged")
            elif eval_result is None:
                print(
                    f"  {qid} docs: [WARN] evaluation failed ({eval_error}), "
                    "using original gold set"
                )
            else:
                print(f"  {qid} docs: gold documents confirmed")

    original_question = question_row
    effective_question = updated_q if updated_q else original_question
    effective_doc_ids = effective_question.get("expected_doc_ids", [])
    effective_facts = effective_question.get("answer_facts", [])

    # Determine corrected status
    gold_answer_updated = original_question.get(
        "gold_answer"
    ) != effective_question.get("gold_answer")
    docs_updated = set(original_question.get("expected_doc_ids", [])) != set(
        effective_question.get("expected_doc_ids", [])
    )
    question_corrected = gold_answer_updated or docs_updated

    # Compute overlapping/unique doc sets for comparison, capped at 15 docs
    # per system. Overlapping docs count toward both systems' totals.
    max_docs_per_system = 15
    set_1 = set(docs_1)
    set_2 = set(docs_2)
    overlapping = [d for d in docs_1 if d in set_2]
    only_1 = [d for d in docs_1 if d not in set_2]
    only_2 = [d for d in docs_2 if d not in set_1]

    if len(overlapping) > max_docs_per_system:
        overlapping = random.sample(overlapping, max_docs_per_system)
        only_1 = []
        only_2 = []
    else:
        remaining = max_docs_per_system - len(overlapping)
        if len(only_1) > remaining:
            only_1 = random.sample(only_1, remaining)
        if len(only_2) > remaining:
            only_2 = random.sample(only_2, remaining)

    effective_gold_set = set(effective_doc_ids)

    # Randomly swap presentation order to reduce positional bias
    swapped = random.choice([True, False])
    if swapped:
        cmp_answer_1, cmp_answer_2 = answer_2, answer_1
        cmp_only_1, cmp_only_2 = only_2, only_1
    else:
        cmp_answer_1, cmp_answer_2 = answer_1, answer_2
        cmp_only_1, cmp_only_2 = only_1, only_2

    # Run comparison and both answer set scorings in parallel
    comparison_result: dict | None = None
    set_1_scores: dict = {}
    set_2_scores: dict = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        comparison_future = executor.submit(
            compare_answers_with_consensus,
            question_row["question"],
            cmp_answer_1,
            cmp_answer_2,
            overlapping,
            cmp_only_1,
            cmp_only_2,
            effective_gold_set,
            document_path_map,
        )
        score_1_future = executor.submit(
            score_answer_set,
            answer_1 or None,
            docs_1,
            effective_doc_ids,
            effective_facts,
        )
        score_2_future = executor.submit(
            score_answer_set,
            answer_2 or None,
            docs_2,
            effective_doc_ids,
            effective_facts,
        )

        try:
            comparison_result = comparison_future.result()
        except Exception:
            comparison_result = None

        try:
            set_1_scores = score_1_future.result()
        except Exception:
            set_1_scores = {
                "completeness_pct": 0.0,
                "document_recall_pct": None,
                "invalid_extra_docs": None,
            }

        try:
            set_2_scores = score_2_future.result()
        except Exception:
            set_2_scores = {
                "completeness_pct": 0.0,
                "document_recall_pct": None,
                "invalid_extra_docs": None,
            }

    if comparison_result is None:
        comparison_result = {
            "preferred_system": "1",
            "effectively_equivalent": True,
            "reason": "comparison failed — all consensus runs returned unusable output",
        }

    # Map comparison result back to original answer file ordering
    if swapped:
        flipped_pref = "2" if comparison_result["preferred_system"] == "1" else "1"
        comparison_result["preferred_system"] = flipped_pref

    comparison_result["reason"] = (
        "Note that the LLM sees the two systems in a random order so the "
        "referenced System 1/2 in the provided reasoning may be out of order. "
        "LLM provided reasoning: " + comparison_result["reason"]
    )

    return updated_q, {
        "question_id": qid,
        "corrected": question_corrected,
        "question_type": question_row.get("question_type"),
        "comparison": comparison_result,
        "answer_set_1": set_1_scores,
        "answer_set_2": set_2_scores,
    }


# =============================================================================
# Statistics & Output
# =============================================================================


def compute_comparative_stats(
    question_results: list[dict],
) -> dict:
    """Compute aggregate comparative stats."""
    n = len(question_results)
    if n == 0:
        return {
            "completed_questions": 0,
            "num_corrected_questions": 0,
            "system_1_preferred_pct": 0.0,
            "system_2_preferred_pct": 0.0,
            "system_1_strongly_preferred_pct": 0.0,
            "system_2_strongly_preferred_pct": 0.0,
            "tie_pct": 0.0,
            "answer_set_1": {
                "average_completeness_pct": 0.0,
                "average_recall_pct": 0.0,
                "average_extra_docs": 0.0,
            },
            "answer_set_2": {
                "average_completeness_pct": 0.0,
                "average_recall_pct": 0.0,
                "average_extra_docs": 0.0,
            },
        }

    # Preference counts (ties still count toward preferred_system)
    sys1_preferred = sum(
        1
        for r in question_results
        if r.get("comparison", {}).get("preferred_system") == "1"
    )
    sys2_preferred = n - sys1_preferred
    ties = sum(
        1
        for r in question_results
        if r.get("comparison", {}).get("effectively_equivalent") is True
    )
    num_corrected = sum(1 for r in question_results if r.get("corrected"))

    # Strong preference: ties don't count toward either system
    non_tie_sys1 = sum(
        1
        for r in question_results
        if r.get("comparison", {}).get("preferred_system") == "1"
        and r.get("comparison", {}).get("effectively_equivalent") is not True
    )
    non_tie_sys2 = sum(
        1
        for r in question_results
        if r.get("comparison", {}).get("preferred_system") == "2"
        and r.get("comparison", {}).get("effectively_equivalent") is not True
    )

    def _avg_set_stats(set_key: str) -> dict:
        completeness_vals = [r[set_key]["completeness_pct"] for r in question_results]
        recall_vals = [
            r[set_key]["document_recall_pct"]
            for r in question_results
            if r[set_key]["document_recall_pct"] is not None
        ]
        extra_vals = [
            r[set_key]["invalid_extra_docs"]
            for r in question_results
            if r[set_key]["invalid_extra_docs"] is not None
        ]
        return {
            "average_completeness_pct": (
                round(sum(completeness_vals) / len(completeness_vals), 2)
                if completeness_vals
                else 0.0
            ),
            "average_recall_pct": (
                round(sum(recall_vals) / len(recall_vals), 2) if recall_vals else 0.0
            ),
            "average_extra_docs": (
                round(sum(extra_vals) / len(extra_vals), 2) if extra_vals else 0.0
            ),
        }

    return {
        "completed_questions": n,
        "num_corrected_questions": num_corrected,
        "system_1_preferred_pct": round(sys1_preferred / n * 100, 2),
        "system_2_preferred_pct": round(sys2_preferred / n * 100, 2),
        "system_1_strongly_preferred_pct": round(non_tie_sys1 / n * 100, 2),
        "system_2_strongly_preferred_pct": round(non_tie_sys2 / n * 100, 2),
        "tie_pct": round(ties / n * 100, 2),
        "answer_set_1": _avg_set_stats("answer_set_1"),
        "answer_set_2": _avg_set_stats("answer_set_2"),
    }


def build_comparative_question_type_stats(
    question_results: list[dict],
    type_order: list[str] | None = None,
) -> dict[str, dict]:
    """Build per-question-type comparative stats."""
    grouped = group_results_by_type(question_results, type_order)
    return {qt: compute_comparative_stats(group) for qt, group in grouped.items()}


def write_comparative_results_snapshot(
    results_file: str,
    output_file: str,
    answer_file_1: str,
    answer_file_2: str,
    question_results: list[dict],
    skip_count: int | str,
    total_questions: int,
    type_order: list[str] | None = None,
) -> None:
    """Write comparative results snapshot to disk atomically."""
    sorted_results = sort_question_results(question_results)
    stats = compute_comparative_stats(question_results)
    results_output = {
        "system_1": answer_file_1,
        "system_2": answer_file_2,
        "updated_question_file": output_file,
        "aggregate_stats": {
            "total_questions": total_questions,
            "skipped_rows": skip_count,
            **stats,
        },
        "question_type_stats": build_comparative_question_type_stats(
            question_results, type_order=type_order
        ),
        "questions": sorted_results,
    }
    write_json_file(results_file, results_output)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two RAG systems' answers head-to-head"
    )
    parser.add_argument(
        "--answer-file-1",
        required=True,
        help="Path to system 1 answers JSONL",
    )
    parser.add_argument(
        "--answer-file-2",
        required=True,
        help="Path to system 2 answers JSONL",
    )
    parser.add_argument(
        "--questions-file",
        default=DEFAULT_QUESTIONS_FILE,
        help=f"Path to questions JSONL file (default: {DEFAULT_QUESTIONS_FILE})",
    )
    parser.add_argument(
        "--results-file",
        default=DEFAULT_RESULTS_FILE,
        help=f"Path to output results JSON (default: {DEFAULT_RESULTS_FILE})",
    )
    parser.add_argument(
        "--updated-questions-file",
        default=DEFAULT_UPDATED_QUESTIONS_FILE,
        help=(
            "Path to output updated questions JSONL "
            f"(default: {DEFAULT_UPDATED_QUESTIONS_FILE})"
        ),
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
        "--resume",
        action="store_true",
        help="Skip questions already in results file",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max questions to process"
    )
    args = parser.parse_args()

    # Validate input files exist
    for path, label in [
        (args.answer_file_1, "answer-file-1"),
        (args.answer_file_2, "answer-file-2"),
        (args.questions_file, "questions-file"),
    ]:
        if not os.path.exists(path):
            print(f"Error: {label} not found: {path}")
            sys.exit(1)

    if args.question_id and args.parallelism != 1:
        print("  [INFO] --question-id set; forcing parallelism=1")
        args.parallelism = 1

    # =========================================================================
    # 1. Load questions and answers
    # =========================================================================

    print(f"Loading questions from {args.questions_file}...")
    questions = load_questions(args.questions_file)
    print(f"  Loaded {len(questions)} questions")

    type_order = build_type_order(questions)

    print(f"Loading system 1 answers from {args.answer_file_1}...")
    answers_1 = load_answers(args.answer_file_1)
    print(f"  Loaded {len(answers_1)} rows")

    print(f"Loading system 2 answers from {args.answer_file_2}...")
    answers_2 = load_answers(args.answer_file_2)
    print(f"  Loaded {len(answers_2)} rows")

    # Build per-qid lookup (last occurrence wins)
    answers_1_by_qid: dict[str, dict] = {}
    for row in answers_1:
        qid = row.get("question_id")
        if qid:
            answers_1_by_qid[qid] = row

    answers_2_by_qid: dict[str, dict] = {}
    for row in answers_2:
        qid = row.get("question_id")
        if qid:
            answers_2_by_qid[qid] = row

    # Find common question IDs present in both answer files and questions
    qids_1 = set(answers_1_by_qid)
    qids_2 = set(answers_2_by_qid)
    qids_q = set(questions)

    common_qids = qids_1 & qids_2 & qids_q
    only_in_1 = (qids_1 & qids_q) - qids_2
    only_in_2 = (qids_2 & qids_q) - qids_1
    not_in_questions = (qids_1 | qids_2) - qids_q

    skip_count = len(only_in_1) + len(only_in_2) + len(not_in_questions)

    print("\n  Answer file overlap summary:")
    print(f"    Unique to system 1 (skipped):     {len(only_in_1)}")
    print(f"    Unique to system 2 (skipped):     {len(only_in_2)}")
    if not_in_questions:
        print(f"    Not in questions file (skipped):  {len(not_in_questions)}")
    print(f"    Common to both systems:            {len(common_qids)}")
    print(f"    Total to process:                  {len(common_qids)}")

    # Sort for deterministic ordering
    valid_qids = sorted(common_qids)

    if args.question_id:
        if args.question_id not in common_qids:
            print(
                f"Error: question_id '{args.question_id}' not found in "
                "common question set"
            )
            sys.exit(1)
        valid_qids = [args.question_id]
        print(f"  Targeting single question: {args.question_id}")

    # =========================================================================
    # 2. Compare with existing results to find new questions
    # =========================================================================

    question_results: list[dict] = []
    completed_qids: set[str] = set()

    if args.question_id:
        if os.path.exists(args.results_file):
            try:
                existing_results = load_json_file(args.results_file)
                for r in existing_results.get("questions", []):
                    rqid = r.get("question_id")
                    question_results.append(r)
                    if rqid and rqid != args.question_id:
                        completed_qids.add(rqid)
            except Exception:
                print(
                    f"  [WARN] Could not load existing results from "
                    f"{args.results_file}, starting fresh"
                )
    elif args.resume and os.path.exists(args.results_file):
        try:
            existing_results = load_json_file(args.results_file)
            for r in existing_results.get("questions", []):
                rqid = r.get("question_id")
                question_results.append(r)
                if rqid:
                    completed_qids.add(rqid)
        except Exception:
            print(
                f"  [WARN] Could not load existing results from "
                f"{args.results_file}, starting fresh"
            )

    valid_qids_set = set(valid_qids)
    new_qids = valid_qids_set - completed_qids
    is_resuming = False

    if completed_qids and not args.question_id:
        overlapping_qids = valid_qids_set & completed_qids
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
        print(f"\n  {len(valid_qids_set)} questions to evaluate")

    # =========================================================================
    # 3. Build and validate UUID path map
    # =========================================================================

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
            answer_sets=[answers_1, answers_2],
            updated_questions=updated_questions,
            uuid_index_cache_file=args.uuid_index_cache_file,
        )
    except ValueError as exc:
        print(f"\nFATAL: {exc}")
        sys.exit(1)

    # =========================================================================
    # 4. Prepare worker pool and incremental output state
    # =========================================================================

    remaining_qids = [qid for qid in valid_qids if qid not in completed_qids]
    if args.limit is not None:
        remaining_qids = remaining_qids[: args.limit]
        print(f"  Processing {len(remaining_qids)} questions (--limit {args.limit})")

    if args.question_id:
        total_questions = len(question_results) + len(valid_qids)
    else:
        total_questions = len(valid_qids)

    display_skip_count: int | str = "N/A" if is_resuming else skip_count

    # Initialize results file
    write_comparative_results_snapshot(
        results_file=args.results_file,
        output_file=args.updated_questions_file,
        answer_file_1=args.answer_file_1,
        answer_file_2=args.answer_file_2,
        question_results=question_results,
        skip_count=display_skip_count,
        total_questions=total_questions,
        type_order=type_order,
    )

    def evaluate_single_question(qid: str) -> tuple[dict | None, dict]:
        """Evaluate a single question comparison."""
        return process_comparative_question(
            qid=qid,
            row_1=answers_1_by_qid[qid],
            row_2=answers_2_by_qid[qid],
            questions=questions,
            document_path_map=document_path_map,
            skip_citation_stripping=args.skip_citation_stripping,
        )

    def handle_completed_question(
        updated_q: dict | None,
        result: dict,
    ) -> None:
        """Record a completed question and flush results to disk."""
        qid = result["question_id"]
        if updated_q:
            updated_questions[qid] = updated_q

        question_results[:] = [
            existing
            for existing in question_results
            if existing.get("question_id") != qid
        ]
        question_results.append(result)

        write_comparative_results_snapshot(
            results_file=args.results_file,
            output_file=args.updated_questions_file,
            answer_file_1=args.answer_file_1,
            answer_file_2=args.answer_file_2,
            question_results=question_results,
            skip_count=display_skip_count,
            total_questions=total_questions,
            type_order=type_order,
        )

    # =========================================================================
    # 5. Run evaluation
    # =========================================================================

    remaining_count = len(remaining_qids)
    if remaining_count == 0:
        print("\nAll questions already evaluated, nothing to do.")
    else:
        if args.parallelism > 1:
            print(
                f"\nEvaluating {remaining_count} questions with "
                f"{args.parallelism} parallel workers"
            )
        else:
            print(f"\nEvaluating {remaining_count} questions sequentially...")

        if args.parallelism <= 1:
            for i, qid in enumerate(remaining_qids, 1):
                print(f"\n[{i}/{remaining_count}] {qid}")
                updated_q, result = evaluate_single_question(qid)
                handle_completed_question(updated_q, result)
        else:
            with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
                futures = {
                    executor.submit(evaluate_single_question, qid): qid
                    for qid in remaining_qids
                }
                for future in as_completed(futures):
                    updated_q, result = future.result()
                    handle_completed_question(updated_q, result)

    # =========================================================================
    # 6. Final sort and write both output files
    # =========================================================================

    print("\nFinalizing output files (sorting and writing results)...")

    print(f"  Writing {args.results_file}...")
    write_comparative_results_snapshot(
        results_file=args.results_file,
        output_file=args.updated_questions_file,
        answer_file_1=args.answer_file_1,
        answer_file_2=args.answer_file_2,
        question_results=question_results,
        skip_count=display_skip_count,
        total_questions=total_questions,
        type_order=type_order,
    )

    # Build corrected qids from results
    corrected_qids: set[str] = set()
    for r in question_results:
        if r.get("corrected"):
            corrected_qids.add(r["question_id"])

    # Write updated questions JSONL
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

    stats = compute_comparative_stats(question_results)

    print("\nDone.")
    print(f"  Questions scored:       {stats['completed_questions']}")
    print(f"  Skipped rows:           {display_skip_count}")
    print(f"  Corrected questions:    {stats['num_corrected_questions']}")
    print(f"  System 1 preferred:          {stats['system_1_preferred_pct']}%")
    print(f"  System 2 preferred:          {stats['system_2_preferred_pct']}%")
    print(f"  System 1 strongly preferred: {stats['system_1_strongly_preferred_pct']}%")
    print(f"  System 2 strongly preferred: {stats['system_2_strongly_preferred_pct']}%")
    print(f"  Tie percentage:              {stats['tie_pct']}%")
    print(
        f"  Set 1 avg completeness: {stats['answer_set_1']['average_completeness_pct']}%"
    )
    print(f"  Set 1 avg recall:       {stats['answer_set_1']['average_recall_pct']}%")
    print(f"  Set 1 avg extra docs:   {stats['answer_set_1']['average_extra_docs']}")
    print(
        f"  Set 2 avg completeness: {stats['answer_set_2']['average_completeness_pct']}%"
    )
    print(f"  Set 2 avg recall:       {stats['answer_set_2']['average_recall_pct']}%")
    print(f"  Set 2 avg extra docs:   {stats['answer_set_2']['average_extra_docs']}")


if __name__ == "__main__":
    main()
