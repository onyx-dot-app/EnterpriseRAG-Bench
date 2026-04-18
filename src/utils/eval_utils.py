"""Shared utilities for answer evaluation scripts."""

import json
import os
import random
import re

from src.llm import Message, get_llm
from src.prompts.answer_evaluation import (
    ANSWER_CITATION_STRIPPING_PROMPT,
    ANSWER_DOC_EVALUATION_PROMPT,
    ANSWER_UPDATOR_PROMPT,
    INDIVIDUAL_FACT_VALIDATOR_PROMPT,
)
from src.utils.cli import confirm_yes_no
from src.utils.document_index import (
    load_document_content_by_uuid,
    load_document_json_by_uuid,
    load_or_build_uuid_index,
    rebuild_uuid_index,
)
from src.utils.json_extraction import extract_json_from_response

_MAX_LLM_RETRIES = 3

DEFAULT_QUESTIONS_FILE = "questions.jsonl"


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


def normalize_document_ids(
    document_ids: object,
    context: str,
) -> list[str]:
    """Validate and normalise a list of document ID strings.

    Returns the list as-is if valid, empty list if None,
    or raises ValueError if the type is unexpected.
    """
    if document_ids is None:
        return []
    if not isinstance(document_ids, list):
        raise ValueError(f"{context}: expected list, got {type(document_ids).__name__}")
    for i, item in enumerate(document_ids):
        if not isinstance(item, str):
            raise ValueError(f"{context}[{i}]: expected str, got {type(item).__name__}")
    return document_ids


def build_document_path_map(
    questions: dict[str, dict],
    answer_sets: list[list[dict]],
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

    for answers in answer_sets:
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
    answer_sets: list[list[dict]],
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
            answer_sets=answer_sets,
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
                answer_sets=answer_sets,
                uuid_index=uuid_index,
                updated_questions=updated_questions,
            )
        except MissingDocumentIdsError as regenerate_exc:
            raise ValueError(
                f"{regenerate_exc} Missing UUIDs remain after regenerating the cache.",
            ) from regenerate_exc

    print(f"  Validated {len(document_path_map)} referenced document ids")
    return document_path_map


# =============================================================================
# Document Formatting
# =============================================================================


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


_DSID_PATTERN = re.compile(r"dsid_[a-f0-9]{20,32}")


def _strip_dsid_references(text: str) -> str:
    """Remove dsid_<hex> strings and clean up surrounding artifacts."""
    cleaned = _DSID_PATTERN.sub("", text)
    # Collapse whitespace runs left behind by removals
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def strip_answer_citations(answer: str) -> str:
    """Strip citations from an answer string using LLM, then remove dsid references."""
    prompt = ANSWER_CITATION_STRIPPING_PROMPT.format(answer_string=answer)

    for attempt in range(_MAX_LLM_RETRIES):
        try:
            llm = get_llm(tools=None, quiet=True)
            messages: list[Message] = [Message(role="user", content=prompt)]

            response = ""
            for chunk in llm.generate(messages):
                if isinstance(chunk, str):
                    response += chunk

            result = response.strip()
            result = result if result else answer
            return _strip_dsid_references(result)
        except Exception:
            if attempt == _MAX_LLM_RETRIES - 1:
                raise
    return _strip_dsid_references(answer)


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

    # Shuffle candidates to avoid positional bias across consensus runs
    shuffled_candidates = list(candidate_doc_ids)
    random.shuffle(shuffled_candidates)

    candidate_docs_text = []
    for dsid in shuffled_candidates:
        doc_data = load_document_json_by_uuid(dsid, document_path_map)
        candidate_docs_text.append(
            format_document_for_doc_evaluation(dsid, doc_data),
        )

    prompt = ANSWER_DOC_EVALUATION_PROMPT.format(
        query=question,
        gold_documents="\n\n".join(gold_docs_text),
        candidate_documents="\n\n".join(candidate_docs_text),
    )

    last_error: str | None = None
    expected_doc_ids = gold_doc_ids + candidate_doc_ids

    for attempt in range(_MAX_LLM_RETRIES):
        try:
            llm = get_llm(tools=None, quiet=True)
            messages: list[Message] = [Message(role="user", content=prompt)]

            response = ""
            for chunk in llm.generate(messages):
                if isinstance(chunk, str):
                    response += chunk
        except Exception as exc:
            last_error = f"LLM call failed ({exc.__class__.__name__})"
            continue

        response = response.strip()

        try:
            parsed = json.loads(extract_json_from_response(response))
        except Exception as exc:
            last_error = f"could not parse JSON output ({exc.__class__.__name__})"
            continue

        if not isinstance(parsed, dict):
            last_error = "output was not a JSON object"
            continue

        normalized: dict[str, dict[str, str]] = {}
        validation_failed = False
        for dsid in expected_doc_ids:
            entry = parsed.get(dsid)
            if not isinstance(entry, dict):
                last_error = f"missing or invalid entry for {dsid}"
                validation_failed = True
                break

            classification = entry.get("classification")
            reason = entry.get("reason")
            if classification not in {"required", "valid", "invalid"}:
                last_error = f"invalid classification for {dsid}"
                validation_failed = True
                break
            if not isinstance(reason, str):
                last_error = f"invalid reason for {dsid}"
                validation_failed = True
                break

            normalized[dsid] = {
                "classification": classification,
                "reason": reason,
            }

        if validation_failed:
            continue

        return (normalized, None)

    return (None, last_error)


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

        # Check if this run agrees with the original gold set:
        # all gold docs must be "required", all candidates must NOT be "required"
        run_required: set[str] = set()
        for dsid in gold_doc_ids:
            entry = eval_result.get(dsid, {})
            if entry.get("classification") == "required":
                run_required.add(dsid)
        for dsid in candidate_doc_ids:
            entry = eval_result.get(dsid, {})
            if entry.get("classification") == "required":
                run_required.add(dsid)
        if run_required == gold_set:
            print(
                f"    Consensus run {run_idx + 1}/{num_runs} "
                f"confirmed gold documents"
            )
            return (eval_result, True, None)

    if not all_results:
        return (None, False, "all consensus runs failed")

    # Majority vote per document with ordinal scoring and gold-biased
    # tie-breaking. Scores: required=2, valid=1, invalid=0.
    _CLS_SCORE = {"required": 2, "valid": 1, "invalid": 0}
    all_doc_ids = gold_doc_ids + candidate_doc_ids
    majority_result: dict[str, dict[str, str]] = {}

    for dsid in all_doc_ids:
        scores: list[int] = []
        reasons_by_cls: dict[str, list[str]] = {
            "required": [],
            "valid": [],
            "invalid": [],
        }

        for run_result in all_results:
            entry = run_result.get(dsid, {})
            cls = entry.get("classification", "valid")
            reason = entry.get("reason", "")
            scores.append(_CLS_SCORE.get(cls, 1))
            reasons_by_cls.setdefault(cls, []).append(reason)

        avg_score = sum(scores) / len(scores)

        # Gold docs: treat as "required" unless majority says "invalid".
        # Candidate docs: tie-break downward.
        if dsid in gold_set:
            if avg_score >= 0.5:
                majority_cls = "required"
            else:
                majority_cls = "invalid"
        else:
            if avg_score > 1.5:
                majority_cls = "required"
            elif avg_score > 0.5:
                majority_cls = "valid"
            else:
                majority_cls = "invalid"

        reasons = reasons_by_cls.get(majority_cls, [])
        majority_result[dsid] = {
            "classification": majority_cls,
            "reason": reasons[0] if reasons else "",
        }

    # Check if majority-voted required set matches original gold set
    majority_required: set[str] = set()
    for dsid in gold_doc_ids:
        entry = majority_result.get(dsid, {})
        if entry.get("classification") == "required":
            majority_required.add(dsid)
    for dsid in candidate_doc_ids:
        entry = majority_result.get(dsid, {})
        if entry.get("classification") == "required":
            majority_required.add(dsid)

    if majority_required == gold_set:
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

    for attempt in range(_MAX_LLM_RETRIES):
        try:
            llm = get_llm(tools=None, quiet=True)
            messages: list[Message] = [Message(role="user", content=prompt)]

            response = ""
            for chunk in llm.generate(messages):
                if isinstance(chunk, str):
                    response += chunk

            result = response.strip()
            return result if result else None
        except Exception:
            if attempt == _MAX_LLM_RETRIES - 1:
                raise
    return None


def validate_single_fact(answer: str, statement: str) -> bool:
    """Check if a single fact is supported by the answer using LLM.

    Returns True if the first line of the model output contains "yes".
    """
    prompt = INDIVIDUAL_FACT_VALIDATOR_PROMPT.format(
        answer=answer,
        statement=statement,
    )

    for attempt in range(_MAX_LLM_RETRIES):
        try:
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
        except Exception:
            if attempt == _MAX_LLM_RETRIES - 1:
                raise
    return False


# =============================================================================
# Helpers
# =============================================================================


def dedupe_doc_ids(doc_ids: list[str]) -> list[str]:
    """Deduplicate document IDs preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for did in doc_ids:
        if did not in seen:
            seen.add(did)
            result.append(did)
    return result


def group_results_by_type(
    question_results: list[dict],
    type_order: list[str] | None = None,
) -> dict[str, list[dict]]:
    """Group question results by question_type with optional ordering.

    Returns an ordered dict where keys follow type_order (if provided),
    with any unseen types appended alphabetically.
    """
    by_type: dict[str, list[dict]] = {}
    for r in question_results:
        qt = r.get("question_type", "unknown")
        by_type.setdefault(qt, []).append(r)

    if type_order:
        ordered_keys = [t for t in type_order if t in by_type]
        remaining = sorted(k for k in by_type if k not in set(type_order))
        ordered_keys.extend(remaining)
    else:
        ordered_keys = sorted(by_type)

    return {qt: by_type[qt] for qt in ordered_keys}


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


def question_sort_key(row: dict) -> tuple[int, str, int]:
    """Sort key for question rows by question_id."""
    qid = row.get("question_id", "")
    match = re.match(r"^(.*?)(\d+)$", qid)
    if match:
        prefix, suffix = match.groups()
        return (0, prefix, int(suffix))
    return (1, qid, 0)


def build_type_order(questions: dict[str, dict]) -> list[str]:
    """Build question type ordering based on first appearance."""
    type_order: list[str] = []
    seen_types: set[str] = set()
    for q in questions.values():
        qt = q.get("question_type", "unknown")
        if qt not in seen_types:
            seen_types.add(qt)
            type_order.append(qt)
    return type_order
