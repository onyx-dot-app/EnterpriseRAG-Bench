"""Evaluate answer files against the gold questions dataset."""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llm import Message, get_llm
from src.paths import QUESTIONS_PATH
from src.prompts.answer_evaluation import (
    ANSWER_CITATION_STRIPPING_PROMPT,
    ANSWER_DOC_EVALUATION_PROMPT,
    ANSWER_UPDATOR_PROMPT,
    INDIVIDUAL_FACT_VALIDATOR_PROMPT,
)
from src.utils.cli import confirm_yes_no
from src.utils.document_index import (
    DEFAULT_UUID_INDEX_CACHE_FILE,
    load_document_content_by_uuid,
    load_document_json_by_uuid,
    load_or_build_uuid_index,
    rebuild_uuid_index,
)
from src.utils.file_io import load_json_file, write_json_file
from src.utils.json_extraction import extract_json_from_response
from src.utils.questions import extract_answer_facts, extract_anti_hallucination_facts

DEFAULT_ANSWER_FILE = "answer_evaluation/answers.jsonl"
DEFAULT_OUTPUT_FILE = "generated_data/questions_updated.jsonl"
DEFAULT_RESULTS_FILE = "answer_evaluation/results.json"


class MissingDocumentIdsError(ValueError):
    """Raised when referenced document ids are missing from the UUID index."""


# =============================================================================
# Data Loading
# =============================================================================


def load_questions(questions_path: str) -> dict[str, dict]:
    """Load questions.jsonl into a dict keyed by question_id."""
    questions: dict[str, dict] = {}
    with open(questions_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            qid = row.get("question_id")
            if qid:
                questions[qid] = row
    return questions


def load_updated_questions(output_path: str) -> dict[str, dict]:
    """Load previously updated question rows keyed by question_id."""
    if not os.path.exists(output_path):
        return {}

    updated_questions: dict[str, dict] = {}
    with open(output_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            qid = row.get("question_id")
            if qid and row.get("updated"):
                updated_questions[qid] = row
    return updated_questions


def load_answers(answer_path: str) -> list[dict]:
    """Load answer file, returning all rows."""
    answers: list[dict] = []
    with open(answer_path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                print(f"  [WARN] Line {i + 1}: invalid JSON, skipping")
                continue
            answers.append(row)
    return answers


def strip_answer_citations(answer: str) -> str:
    """Strip citations from an answer string using LLM."""
    prompt = ANSWER_CITATION_STRIPPING_PROMPT.format(answer_string=answer)
    llm = get_llm(tools=None, quiet=True)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    result = response.strip()
    return result if result else answer


def strip_citations_from_answers(answers: list[dict]) -> list[dict]:
    """Strip citations from all answer strings in parallel."""
    rows_with_answers = [
        (i, row) for i, row in enumerate(answers) if row.get("answer")
    ]
    if not rows_with_answers:
        return answers

    max_workers = min(len(rows_with_answers), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(strip_answer_citations, row["answer"]): i
            for i, row in rows_with_answers
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                answers[idx]["answer"] = future.result()
            except Exception:
                print(
                    f"  [WARN] Citation stripping failed for row {idx + 1}, "
                    "using original answer"
                )

    return answers


def normalize_document_ids(document_ids: object, context: str) -> list[str]:
    """Validate and normalize a list of document ids."""
    if document_ids is None:
        return []
    if not isinstance(document_ids, list):
        raise ValueError(
            f"{context} must be a list of document ids, got "
            f"{type(document_ids).__name__}",
        )

    normalized: list[str] = []
    for i, dsid in enumerate(document_ids, 1):
        if not isinstance(dsid, str) or not dsid:
            raise ValueError(
                f"{context} has invalid document id at position {i}: {dsid!r}",
            )
        normalized.append(dsid)
    return normalized


def build_document_path_map(
    questions: dict[str, dict],
    answers: list[dict],
    uuid_index: dict[str, str],
    updated_questions: dict[str, dict] | None = None,
) -> dict[str, str]:
    """Build a referenced-document id -> relative path map or fail loudly."""
    referenced_ids: set[str] = set()

    for qid, row in questions.items():
        referenced_ids.update(
            normalize_document_ids(
                row.get("expected_doc_ids"),
                f"Question {qid} expected_doc_ids",
            ),
        )

    for i, row in enumerate(answers, 1):
        qid = row.get("question_id") or f"row-{i}"
        referenced_ids.update(
            normalize_document_ids(
                row.get("document_ids"),
                f"Answer {qid} document_ids",
            ),
        )

    for qid, row in (updated_questions or {}).items():
        referenced_ids.update(
            normalize_document_ids(
                row.get("expected_doc_ids"),
                f"Updated question {qid} expected_doc_ids",
            ),
        )

    missing_ids = sorted(dsid for dsid in referenced_ids if dsid not in uuid_index)
    if missing_ids:
        preview = ", ".join(missing_ids[:20])
        remainder = len(missing_ids) - 20
        if remainder > 0:
            preview = f"{preview}, ... (+{remainder} more)"
        raise MissingDocumentIdsError(
            "Referenced document ids missing from the source index. "
            f"Underlying data is invalid: {preview}"
        )

    return {dsid: uuid_index[dsid] for dsid in sorted(referenced_ids)}


def resolve_document_path_map(
    questions: dict[str, dict],
    answers: list[dict],
    updated_questions: dict[str, dict],
    uuid_index_cache_file: str,
) -> dict[str, str]:
    """Build the referenced document path map, optionally regenerating cache."""
    print("Loading UUID index...")
    uuid_index = load_or_build_uuid_index(uuid_index_cache_file)
    print(f"  Indexed {len(uuid_index)} documents")

    print("Validating referenced document IDs...")
    try:
        document_path_map = build_document_path_map(
            questions=questions,
            answers=answers,
            uuid_index=uuid_index,
            updated_questions=updated_questions,
        )
    except MissingDocumentIdsError as exc:
        print(f"\n  [WARN] {exc}")
        try:
            should_regenerate = confirm_yes_no(
                "Referenced document IDs are missing from the UUID index cache. "
                "Regenerate the cache now?",
                default=False,
                retry_on_invalid=True,
            )
        except EOFError:
            should_regenerate = False

        if not should_regenerate:
            raise ValueError(
                f"{exc} Cache regeneration declined; cannot continue.",
            ) from exc

        print(f"\nRegenerating UUID index cache at {uuid_index_cache_file}...")
        uuid_index = rebuild_uuid_index(uuid_index_cache_file)

        try:
            document_path_map = build_document_path_map(
                questions=questions,
                answers=answers,
                uuid_index=uuid_index,
                updated_questions=updated_questions,
            )
        except MissingDocumentIdsError as regenerate_exc:
            raise ValueError(
                f"{regenerate_exc} Missing UUIDs remain after regenerating the cache.",
            ) from regenerate_exc

    print(f"  Validated {len(document_path_map)} referenced document ids")
    return document_path_map


def format_document_for_doc_evaluation(dsid: str, document_data: dict) -> str:
    """Format a document entry for ANSWER_DOC_EVALUATION_PROMPT."""
    document_body = json.dumps(document_data, indent=2, ensure_ascii=False)
    return f"Document ID: {dsid}\n```\n{document_body}\n```"


def format_document_for_answer_update(title: str, content: str) -> str:
    """Format a document entry for ANSWER_UPDATOR_PROMPT."""
    return "\n".join(part for part in (title, content) if part)


# =============================================================================
# LLM Evaluation
# =============================================================================


def evaluate_documents(
    question: str,
    gold_doc_ids: list[str],
    candidate_doc_ids: list[str],
    document_path_map: dict[str, str],
) -> tuple[dict[str, dict[str, str]] | None, str | None]:
    """Evaluate candidate documents against gold documents using LLM.

    Returns a normalized dict mapping each dsid to
    {"classification": ..., "reason": ...}, or None plus an error string if the
    LLM output cannot be parsed in the expected shape.
    """
    gold_docs_text = []
    for dsid in gold_doc_ids:
        doc_data = load_document_json_by_uuid(dsid, document_path_map)
        gold_docs_text.append(format_document_for_doc_evaluation(dsid, doc_data))

    candidate_docs_text = []
    for dsid in candidate_doc_ids:
        doc_data = load_document_json_by_uuid(dsid, document_path_map)
        candidate_docs_text.append(
            format_document_for_doc_evaluation(dsid, doc_data),
        )

    prompt = ANSWER_DOC_EVALUATION_PROMPT.format(
        query=question,
        gold_documents="\n\n".join(gold_docs_text),
        candidate_documents="\n\n".join(candidate_docs_text),
    )

    llm = get_llm(tools=None, quiet=True)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    response = response.strip()

    try:
        parsed = json.loads(extract_json_from_response(response))
    except Exception as exc:
        return (None, f"could not parse JSON output ({exc.__class__.__name__})")

    if not isinstance(parsed, dict):
        return (None, "output was not a JSON object")

    normalized: dict[str, dict[str, str]] = {}
    expected_doc_ids = gold_doc_ids + candidate_doc_ids
    for dsid in expected_doc_ids:
        entry = parsed.get(dsid)
        if not isinstance(entry, dict):
            return (None, f"missing or invalid entry for {dsid}")

        classification = entry.get("classification")
        reason = entry.get("reason")
        if classification not in {"valid", "invalid"}:
            return (None, f"invalid classification for {dsid}")
        if not isinstance(reason, str):
            return (None, f"invalid reason for {dsid}")

        normalized[dsid] = {
            "classification": classification,
            "reason": reason,
        }

    return (normalized, None)


def evaluate_documents_with_consensus(
    question: str,
    gold_doc_ids: list[str],
    candidate_doc_ids: list[str],
    document_path_map: dict[str, str],
) -> tuple[dict[str, dict[str, str]] | None, bool, str | None]:
    """Run document evaluation 3 times and return majority-vote result.

    Returns (eval_result, gold_confirmed, error_string).
    If gold_confirmed is True, the original gold documents were validated
    as correct and no update is needed.

    Per-document tie-breaking favors the original gold set: gold docs stay
    valid on a tie, candidate docs stay invalid on a tie.
    """
    num_runs = 3
    all_results: list[dict[str, dict[str, str]]] = []
    gold_set = set(gold_doc_ids)

    for run_idx in range(num_runs):
        eval_result, eval_error = evaluate_documents(
            question=question,
            gold_doc_ids=gold_doc_ids,
            candidate_doc_ids=candidate_doc_ids,
            document_path_map=document_path_map,
        )
        if eval_result is None:
            print(
                f"    [WARN] Consensus run {run_idx + 1}/{num_runs} "
                f"failed: {eval_error}"
            )
            continue
        all_results.append(eval_result)

        # Check if this run agrees with the original gold set
        run_valid: set[str] = set()
        for dsid in gold_doc_ids:
            entry = eval_result.get(dsid, {})
            if entry.get("classification", "valid") != "invalid":
                run_valid.add(dsid)
        for dsid in candidate_doc_ids:
            entry = eval_result.get(dsid, {})
            if entry.get("classification") == "valid":
                run_valid.add(dsid)
        if run_valid == gold_set:
            print(
                f"    Consensus run {run_idx + 1}/{num_runs} "
                f"confirmed gold documents"
            )
            return (eval_result, True, None)

    if not all_results:
        return (None, False, "all consensus runs failed")

    # Majority vote per document with gold-biased tie-breaking
    all_doc_ids = gold_doc_ids + candidate_doc_ids
    majority_result: dict[str, dict[str, str]] = {}

    for dsid in all_doc_ids:
        valid_count = 0
        invalid_count = 0
        valid_reasons: list[str] = []
        invalid_reasons: list[str] = []

        for run_result in all_results:
            entry = run_result.get(dsid, {})
            cls = entry.get("classification", "valid")
            reason = entry.get("reason", "")
            if cls == "valid":
                valid_count += 1
                valid_reasons.append(reason)
            else:
                invalid_count += 1
                invalid_reasons.append(reason)

        # Ties favor the original gold set: keep gold docs, reject candidates
        if dsid in gold_set:
            majority_cls = "valid" if valid_count >= invalid_count else "invalid"
        else:
            majority_cls = "valid" if valid_count > invalid_count else "invalid"

        reasons = valid_reasons if majority_cls == "valid" else invalid_reasons
        majority_result[dsid] = {
            "classification": majority_cls,
            "reason": reasons[0] if reasons else "",
        }

    # Check if majority-voted result matches original gold set
    majority_valid: set[str] = set()
    for dsid in gold_doc_ids:
        entry = majority_result.get(dsid, {})
        if entry.get("classification", "valid") != "invalid":
            majority_valid.add(dsid)
    for dsid in candidate_doc_ids:
        entry = majority_result.get(dsid, {})
        if entry.get("classification") == "valid":
            majority_valid.add(dsid)

    if majority_valid == gold_set:
        print("    Consensus majority vote confirmed gold documents")
        return (majority_result, True, None)

    print(
        f"    Consensus: {len(all_results)}/{num_runs} runs completed, "
        f"majority vote differs from gold"
    )
    return (majority_result, False, None)


def update_gold_answer(
    question: str,
    previous_gold_answer: str,
    valid_doc_ids: list[str],
    document_path_map: dict[str, str],
) -> str | None:
    """Generate an updated gold answer based on the new valid document set."""
    docs_text = []
    for dsid in valid_doc_ids:
        title, content = load_document_content_by_uuid(dsid, document_path_map)
        docs_text.append(format_document_for_answer_update(title, content))

    if not docs_text:
        return None

    prompt = ANSWER_UPDATOR_PROMPT.format(
        previous_gold_answer=previous_gold_answer,
        reference_documents="\n\n".join(docs_text),
        query=question,
    )

    llm = get_llm(tools=None, quiet=True)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    result = response.strip()
    return result if result else None


def validate_answer_completeness(
    answer: str,
    facts: list[str],
) -> int | None:
    """Validate how many facts are supported by the answer using LLM.

    Each fact is evaluated independently in parallel. A fact counts as valid
    only if the first line of the model output contains "yes" in any casing.
    Returns the number of validated facts, or None on failure.
    """
    if not facts:
        return 0

    def validate_single_fact(statement: str) -> bool:
        prompt = INDIVIDUAL_FACT_VALIDATOR_PROMPT.format(
            answer=answer,
            statement=statement,
        )

        llm = get_llm(tools=None, quiet=True)
        messages: list[Message] = [Message(role="user", content=prompt)]

        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                response += chunk

        first_line = (
            response.strip().splitlines()[0].strip() if response.strip() else ""
        )
        return re.search(r"\byes\b", first_line, re.IGNORECASE) is not None

    max_workers = min(len(facts), 8)
    validated_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(validate_single_fact, statement) for statement in facts
        ]

        for future in as_completed(futures):
            try:
                if future.result():
                    validated_count += 1
            except Exception:
                return None

    return validated_count


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

    # Dedupe answer doc_ids preserving order
    seen: set[str] = set()
    deduped_doc_ids: list[str] = []
    for did in answer_doc_ids:
        if did not in seen:
            seen.add(did)
            deduped_doc_ids.append(did)

    gold_set = set(gold_doc_ids)
    answer_set = set(deduped_doc_ids)

    # If the document sets are identical, no evaluation needed
    if gold_set == answer_set:
        return (f"OK {qid}: document set matches gold", None)

    # Find candidate docs that are not in the gold set
    candidate_only = [d for d in deduped_doc_ids if d not in gold_set]

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

    # Determine the new valid document set
    valid_doc_ids: list[str] = []
    for dsid in gold_doc_ids:
        entry = update_reasons.get(dsid, {})
        if entry.get("classification", "valid") != "invalid":
            valid_doc_ids.append(dsid)

    for dsid in candidate_only:
        entry = update_reasons.get(dsid, {})
        if entry.get("classification") == "valid":
            valid_doc_ids.append(dsid)

    if not valid_doc_ids:
        return (
            "[WARN] document evaluation marked no documents as valid; "
            "using original gold set",
            None,
        )

    new_set = set(valid_doc_ids)
    docs_changed = new_set != gold_set

    # Build updated question row
    updated_row = dict(question_row)
    updated_row["updated"] = True
    updated_row["update_reasons"] = update_reasons

    if docs_changed:
        updated_row["expected_doc_ids"] = valid_doc_ids

        # Regenerate gold answer with updated document set
        new_answer = update_gold_answer(
            question=question_row["question"],
            previous_gold_answer=question_row.get("gold_answer", ""),
            valid_doc_ids=valid_doc_ids,
            document_path_map=document_path_map,
        )
        if new_answer:
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
            f"UPDATED {qid}: document set changed ({len(gold_doc_ids)} -> {len(valid_doc_ids)} docs)",
            updated_row,
        )
    else:
        return (
            f"EVALUATED {qid}: document set unchanged after evaluation",
            updated_row,
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
    expected_doc_ids = question_data.get("expected_doc_ids", [])
    answer_facts = question_data.get("answer_facts", [])
    question_type = original_question_data.get("question_type")
    gold_answer_updated = original_question_data.get(
        "gold_answer"
    ) != question_data.get("gold_answer")

    # Dedupe answer doc_ids
    seen: set[str] = set()
    deduped_doc_ids: list[str] = []
    for did in answer_doc_ids:
        if did not in seen:
            seen.add(did)
            deduped_doc_ids.append(did)

    expected_set = set(expected_doc_ids)
    answer_doc_set = set(deduped_doc_ids)

    # Document recall
    if expected_set:
        correct_docs = answer_doc_set & expected_set
        document_recall_pct = len(correct_docs) / len(expected_set) * 100
    else:
        document_recall_pct = 100.0

    # Invalid extra documents
    invalid_extra_docs = len(answer_doc_set - expected_set)

    # Answer completeness and correctness
    if answer_text and answer_facts:
        validated_count = validate_answer_completeness(answer_text, answer_facts)
        if validated_count is not None:
            validated_count = min(validated_count, len(answer_facts))
            completeness_pct = validated_count / len(answer_facts) * 100
            answer_correct = validated_count == len(answer_facts)
        else:
            completeness_pct = 0.0
            answer_correct = False
    elif answer_text and not answer_facts:
        # No facts to validate against, can't measure completeness
        completeness_pct = 100.0
        answer_correct = True
    else:
        # No answer provided
        completeness_pct = 0.0
        answer_correct = False

    return {
        "question_id": qid,
        "question_type": question_type,
        "gold_answer_updated": gold_answer_updated,
        "answer_correct": answer_correct,
        "completeness_pct": round(completeness_pct, 2),
        "document_recall_pct": round(document_recall_pct, 2),
        "invalid_extra_docs": invalid_extra_docs,
    }


def compute_stats_for_group(results: list[dict]) -> dict[str, float | int]:
    """Compute average stats for a group of question results."""
    n = len(results)
    if n == 0:
        return {
            "count": 0,
            "average_correctness_pct": 0.0,
            "average_completeness_pct": 0.0,
            "average_recall_pct": 0.0,
            "average_extra_docs": 0.0,
        }
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
        "average_recall_pct": round(
            sum(r["document_recall_pct"] for r in results) / n,
            2,
        ),
        "average_extra_docs": round(
            sum(r["invalid_extra_docs"] for r in results) / n,
            2,
        ),
    }


def build_question_type_stats(
    question_results: list[dict],
) -> dict[str, dict[str, float | int]]:
    """Build per-question-type stats breakdown."""
    by_type: dict[str, list[dict]] = {}
    for r in question_results:
        qt = r.get("question_type", "unknown")
        by_type.setdefault(qt, []).append(r)
    return {qt: compute_stats_for_group(group) for qt, group in sorted(by_type.items())}


def build_aggregate_stats(
    question_results: list[dict],
    skip_count: int,
    total_questions: int,
) -> dict[str, float | int]:
    """Build aggregate stats for the current evaluation snapshot."""
    stats = compute_stats_for_group(question_results)
    num_corrected = sum(1 for r in question_results if r.get("gold_answer_updated"))
    return {
        "total_questions": total_questions,
        "completed_questions": stats.pop("count"),
        "skipped_rows": skip_count,
        "num_corrected_questions": num_corrected,
        **stats,
    }


def sort_question_results(question_results: list[dict]) -> list[dict]:
    """Return question results sorted by question_id in ascending order."""

    def sort_key(result: dict) -> tuple[int, str, int]:
        qid = result.get("question_id", "")
        match = re.match(r"^(.*?)(\d+)$", qid)
        if match:
            prefix, suffix = match.groups()
            return (0, prefix, int(suffix))
        return (1, qid, 0)

    return sorted(question_results, key=sort_key)


def write_results_snapshot(
    results_file: str,
    output_file: str,
    question_results: list[dict],
    skip_count: int,
    total_questions: int,
) -> None:
    """Write the current results snapshot to disk atomically."""
    sorted_question_results = sort_question_results(question_results)
    results_output = {
        "updated_question_file": output_file,
        "aggregate_stats": build_aggregate_stats(
            question_results=question_results,
            skip_count=skip_count,
            total_questions=total_questions,
        ),
        "question_type_stats": build_question_type_stats(question_results),
        "questions": sorted_question_results,
    }
    write_json_file(results_file, results_output)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate answer files against gold questions"
    )
    parser.add_argument(
        "--answer-file",
        default=DEFAULT_ANSWER_FILE,
        help=f"Path to answers JSONL file (default: {DEFAULT_ANSWER_FILE})",
    )
    parser.add_argument(
        "--questions-file",
        default=QUESTIONS_PATH,
        help=f"Path to questions JSONL file (default: {QUESTIONS_PATH})",
    )
    parser.add_argument(
        "--output-file",
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
    args = parser.parse_args()

    # Validate input files exist
    if not os.path.exists(args.answer_file):
        print(f"Error: answer file not found: {args.answer_file}")
        sys.exit(1)
    if not os.path.exists(args.questions_file):
        print(f"Error: questions file not found: {args.questions_file}")
        sys.exit(1)

    if args.question_id and args.parallelism != 1:
        print("  [INFO] --question-id set; forcing parallelism=1")
        args.parallelism = 1

    # Load data
    print(f"Loading questions from {args.questions_file}...")
    questions = load_questions(args.questions_file)
    print(f"  Loaded {len(questions)} questions")

    print(f"Loading answers from {args.answer_file}...")
    answers = load_answers(args.answer_file)
    print(f"  Loaded {len(answers)} answer rows")

    print("Stripping citations from answers...")
    answers = strip_citations_from_answers(answers)
    print("  Done stripping citations")

    updated_questions = load_updated_questions(args.output_file)
    if updated_questions:
        print(
            f"  Loaded {len(updated_questions)} updated questions from "
            f"{args.output_file}"
        )

    try:
        document_path_map = resolve_document_path_map(
            questions=questions,
            answers=answers,
            updated_questions=updated_questions,
            uuid_index_cache_file=args.uuid_index_cache_file,
        )
    except ValueError as exc:
        print(f"\nFATAL: {exc}")
        sys.exit(1)

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
    # Resume from existing results if available
    # =========================================================================

    if args.question_id:
        updated_questions.pop(args.question_id, None)

    question_results: list[dict] = []
    completed_qids: set[str] = set()

    if os.path.exists(args.results_file):
        try:
            existing_results = load_json_file(args.results_file)
            for r in existing_results.get("questions", []):
                qid = r.get("question_id")
                question_results.append(r)
                if qid and qid != args.question_id:
                    completed_qids.add(qid)
            if completed_qids:
                print(
                    f"\n  Resuming: found {len(completed_qids)} already-evaluated questions in {args.results_file}"
                )
        except Exception:
            print(
                f"\n  [WARN] Could not load existing results from {args.results_file}, starting fresh"
            )

    # Filter out already-completed questions
    remaining_rows = [
        row for row in valid_rows if row["question_id"] not in completed_qids
    ]
    if args.question_id:
        total_questions = len(question_results) + len(valid_rows)
    else:
        total_questions = len(valid_rows)

    # =========================================================================
    # Per-question evaluation: document eval + answer scoring
    # =========================================================================

    def evaluate_single_question(
        row: dict,
    ) -> tuple[dict | None, dict]:
        """Evaluate a single question: doc eval then answer scoring."""
        qid = row["question_id"]
        updated_q: dict | None = None

        if row.get("document_ids"):
            status, updated_q = process_question_docs(
                row,
                questions,
                document_path_map,
            )
            print(f"  {qid} docs: {status}")

        original_question = questions[qid]
        effective_question = updated_q if updated_q else original_question
        result = score_answer(row, effective_question, original_question)
        print(
            f"  {qid} score: correct={result['answer_correct']}"
            f"  completeness={result['completeness_pct']}%"
            f"  recall={result['document_recall_pct']}%"
            f"  extra_docs={result['invalid_extra_docs']}"
        )
        return updated_q, result

    # Keep results.json populated as questions finish. All writes happen here
    # on the main thread, even when evaluation itself runs in parallel.
    print(f"\nInitializing results file at {args.results_file}...")
    write_results_snapshot(
        results_file=args.results_file,
        output_file=args.output_file,
        question_results=question_results,
        skip_count=skip_count,
        total_questions=total_questions,
    )

    def handle_completed_question(
        updated_q: dict | None,
        result: dict,
    ) -> None:
        """Record a completed question and flush the snapshot to disk."""
        if updated_q:
            updated_questions[updated_q["question_id"]] = updated_q

        question_results[:] = [
            existing
            for existing in question_results
            if existing.get("question_id") != result["question_id"]
        ]
        question_results.append(result)
        write_results_snapshot(
            results_file=args.results_file,
            output_file=args.output_file,
            question_results=question_results,
            skip_count=skip_count,
            total_questions=total_questions,
        )

    remaining_count = len(remaining_rows)
    if remaining_count == 0:
        print("\nAll questions already evaluated, nothing to do.")
    else:
        print(
            f"\nEvaluating {remaining_count} remaining questions (parallelism={args.parallelism})..."
        )

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
                for future in as_completed(futures):
                    updated_q, result = future.result()
                    handle_completed_question(updated_q, result)

    # Write updated questions file
    print(f"\nWriting updated questions to {args.output_file}...")
    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    with open(args.output_file, "w") as f:
        with open(args.questions_file) as qf:
            for line in qf:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                qid = row.get("question_id")
                if qid and qid in updated_questions:
                    f.write(json.dumps(updated_questions[qid]) + "\n")
                else:
                    f.write(json.dumps(row) + "\n")

    # =========================================================================
    # Aggregate stats and write results
    # =========================================================================

    aggregate_stats = build_aggregate_stats(
        question_results=question_results,
        skip_count=skip_count,
        total_questions=total_questions,
    )

    print(f"\nFinalizing results at {args.results_file}...")
    write_results_snapshot(
        results_file=args.results_file,
        output_file=args.output_file,
        question_results=question_results,
        skip_count=skip_count,
        total_questions=total_questions,
    )

    print(f"\nDone.")
    print(f"  Questions scored:    {aggregate_stats['completed_questions']}")
    print(f"  Skipped rows:        {skip_count}")
    print(f"  Corrected questions: {aggregate_stats['num_corrected_questions']}")
    print(f"  Avg correctness:     {aggregate_stats['average_correctness_pct']}%")
    print(f"  Avg completeness:    {aggregate_stats['average_completeness_pct']}%")
    print(f"  Avg recall:          {aggregate_stats['average_recall_pct']}%")
    print(f"  Avg extra docs:      {aggregate_stats['average_extra_docs']}")


if __name__ == "__main__":
    main()
