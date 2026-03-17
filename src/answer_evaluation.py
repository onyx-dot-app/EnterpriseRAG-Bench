"""Evaluate answer files against the gold questions dataset."""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llm import Message, get_llm
from src.paths import QUESTIONS_PATH, SOURCES_DIR
from src.prompts.answer_evaluation import (
    ANSWER_DOC_EVALUATION_PROMPT,
    ANSWER_UPDATOR_PROMPT,
    INDIVIDUAL_FACT_VALIDATOR_PROMPT,
)
from src.utils.document_content import extract_document_content
from src.utils.file_io import load_json_file, write_json_file
from src.utils.json_extraction import extract_json_from_response
from src.utils.questions import extract_answer_facts, extract_anti_hallucination_facts

DEFAULT_ANSWER_FILE = "answer_evaluation/answers.jsonl"
DEFAULT_OUTPUT_FILE = "generated_data/questions_updated.jsonl"
DEFAULT_RESULTS_FILE = "answer_evaluation/results.json"


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


UUID_INDEX_PATH = os.path.join("generation_cache", "uuid_index.json")


def build_uuid_index() -> dict[str, str]:
    """Build a mapping of dataset_doc_uuid -> relative path from SOURCES_DIR."""
    index: dict[str, str] = {}
    for root, _dirs, files in os.walk(SOURCES_DIR):
        for filename in files:
            if not filename.endswith(".json"):
                continue
            full_path = os.path.join(root, filename)
            try:
                doc = load_json_file(full_path)
                uuid = doc.get("dataset_doc_uuid")
                if uuid:
                    rel_path = os.path.relpath(full_path, SOURCES_DIR)
                    index[uuid] = rel_path
            except Exception:
                continue
    return index


def load_or_build_uuid_index() -> dict[str, str]:
    """Load UUID index from cache, or build and save it."""
    if os.path.exists(UUID_INDEX_PATH):
        print(f"  Loading UUID index from {UUID_INDEX_PATH}...")
        return load_json_file(UUID_INDEX_PATH)

    print("  Building UUID index (first run, this may take a moment)...")
    index = build_uuid_index()
    os.makedirs(os.path.dirname(UUID_INDEX_PATH), exist_ok=True)
    write_json_file(UUID_INDEX_PATH, index)
    print(f"  Saved UUID index with {len(index)} entries to {UUID_INDEX_PATH}")
    return index


def load_document_content(dsid: str, uuid_index: dict[str, str]) -> str | None:
    """Load document content by dsid, returning a formatted string or None."""
    rel_path = uuid_index.get(dsid)
    if not rel_path:
        return None
    full_path = os.path.join(SOURCES_DIR, rel_path)
    try:
        doc_data = load_json_file(full_path)
        title, content = extract_document_content(doc_data)
        return f"[{dsid}] {title}\n{content}"
    except Exception:
        return None


# =============================================================================
# LLM Evaluation
# =============================================================================


def evaluate_documents(
    question: str,
    gold_doc_ids: list[str],
    candidate_doc_ids: list[str],
    uuid_index: dict[str, str],
) -> dict[str, dict[str, str]] | None:
    """Evaluate candidate documents against gold documents using LLM.

    Returns a dict mapping each dsid to {"classification": ..., "reason": ...},
    or None on failure.
    """
    gold_docs_text = []
    for dsid in gold_doc_ids:
        content = load_document_content(dsid, uuid_index)
        if content:
            gold_docs_text.append(content)
        else:
            gold_docs_text.append(f"[{dsid}] (document not found)")

    candidate_docs_text = []
    for dsid in candidate_doc_ids:
        content = load_document_content(dsid, uuid_index)
        if content:
            candidate_docs_text.append(content)
        else:
            candidate_docs_text.append(f"[{dsid}] (document not found)")

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
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None

    return parsed


def update_gold_answer(
    question: str,
    previous_gold_answer: str,
    valid_doc_ids: list[str],
    uuid_index: dict[str, str],
) -> str | None:
    """Generate an updated gold answer based on the new valid document set."""
    docs_text = []
    for dsid in valid_doc_ids:
        content = load_document_content(dsid, uuid_index)
        if content:
            docs_text.append(content)

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

    Returns the number of validated facts, or None on failure.
    """
    if not facts:
        return 0

    prompt = INDIVIDUAL_FACT_VALIDATOR_PROMPT.format(
        answer=answer,
        statements=json.dumps(facts),
    )

    llm = get_llm(tools=None, quiet=True)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    response = response.strip()

    try:
        return int(response)
    except ValueError:
        # Try to extract a number from the response
        import re
        match = re.search(r"\d+", response)
        if match:
            return int(match.group())
        return None


# =============================================================================
# Per-Question Processing
# =============================================================================


def process_question_docs(
    answer_row: dict,
    questions: dict[str, dict],
    uuid_index: dict[str, str],
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

    # Evaluate all documents (gold + candidates)
    eval_result = evaluate_documents(
        question=question_row["question"],
        gold_doc_ids=gold_doc_ids,
        candidate_doc_ids=candidate_only,
        uuid_index=uuid_index,
    )

    if eval_result is None:
        return (f"ERROR {qid}: LLM evaluation failed", None)

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
            uuid_index=uuid_index,
        )
        if new_answer:
            updated_row["gold_answer"] = new_answer

            # Re-extract facts for the updated gold answer
            original_facts = question_row.get("answer_facts", [])

            # Preserve anti-hallucination guard facts from the original set
            anti_hallucination_facts = extract_anti_hallucination_facts(
                original_facts, quiet=True,
            ) or []

            # Extract new facts from the updated gold answer
            new_facts = extract_answer_facts(
                question_row["question"], new_answer, quiet=True,
            ) or []

            # Combine: new facts + anti-hallucination guards (deduped)
            new_facts_set = set(new_facts)
            combined_facts = list(new_facts)
            for fact in anti_hallucination_facts:
                if fact not in new_facts_set:
                    combined_facts.append(fact)

            updated_row["answer_facts"] = combined_facts

        return (f"UPDATED {qid}: document set changed ({len(gold_doc_ids)} -> {len(valid_doc_ids)} docs)", updated_row)
    else:
        return (f"EVALUATED {qid}: document set unchanged after evaluation", updated_row)


def score_answer(
    answer_row: dict,
    question_data: dict,
) -> dict:
    """Score a single answer against its question data.

    Returns a dict with per-question metrics.
    """
    qid = answer_row["question_id"]
    answer_text = answer_row.get("answer")
    answer_doc_ids = answer_row.get("document_ids") or []
    expected_doc_ids = question_data.get("expected_doc_ids", [])
    answer_facts = question_data.get("answer_facts", [])

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
        "answer_correct": answer_correct,
        "completeness_pct": round(completeness_pct, 2),
        "document_recall_pct": round(document_recall_pct, 2),
        "invalid_extra_docs": invalid_extra_docs,
    }


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate answer files against gold questions")
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
        "--parallelism",
        type=int,
        default=1,
        help="Number of parallel evaluation threads (default: 1)",
    )
    args = parser.parse_args()

    # Validate input files exist
    if not os.path.exists(args.answer_file):
        print(f"Error: answer file not found: {args.answer_file}")
        sys.exit(1)
    if not os.path.exists(args.questions_file):
        print(f"Error: questions file not found: {args.questions_file}")
        sys.exit(1)

    # Load data
    print(f"Loading questions from {args.questions_file}...")
    questions = load_questions(args.questions_file)
    print(f"  Loaded {len(questions)} questions")

    print(f"Loading answers from {args.answer_file}...")
    answers = load_answers(args.answer_file)
    print(f"  Loaded {len(answers)} answer rows")

    print("Loading UUID index...")
    uuid_index = load_or_build_uuid_index()
    print(f"  Indexed {len(uuid_index)} documents")

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

    # =========================================================================
    # Phase 1: Document evaluation
    # =========================================================================

    rows_with_docs = [r for r in valid_rows if r.get("document_ids")]
    print(f"\n  {len(rows_with_docs)} rows have document_ids to evaluate")

    updated_questions: dict[str, dict] = {}
    doc_stats = {"ok": 0, "updated": 0, "evaluated": 0, "errors": 0}

    if rows_with_docs:
        print(f"\nPhase 1: Document evaluation (parallelism={args.parallelism})...")

        def run_doc_eval(row: dict) -> tuple[str, dict | None]:
            return process_question_docs(row, questions, uuid_index)

        if args.parallelism <= 1:
            for row in rows_with_docs:
                status, updated_row = run_doc_eval(row)
                print(f"  {status}")
                if updated_row:
                    updated_questions[updated_row["question_id"]] = updated_row
                if status.startswith("OK"):
                    doc_stats["ok"] += 1
                elif status.startswith("UPDATED"):
                    doc_stats["updated"] += 1
                elif status.startswith("EVALUATED"):
                    doc_stats["evaluated"] += 1
                else:
                    doc_stats["errors"] += 1
        else:
            with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
                futures = {
                    executor.submit(run_doc_eval, row): row
                    for row in rows_with_docs
                }
                for future in as_completed(futures):
                    status, updated_row = future.result()
                    print(f"  {status}")
                    if updated_row:
                        updated_questions[updated_row["question_id"]] = updated_row
                    if status.startswith("OK"):
                        doc_stats["ok"] += 1
                    elif status.startswith("UPDATED"):
                        doc_stats["updated"] += 1
                    elif status.startswith("EVALUATED"):
                        doc_stats["evaluated"] += 1
                    else:
                        doc_stats["errors"] += 1

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
    # Phase 2: Answer scoring
    # =========================================================================

    print(f"\nPhase 2: Answer scoring (parallelism={args.parallelism})...")

    # Build effective question data: use updated version if available, else original
    def get_effective_question(qid: str) -> dict:
        return updated_questions.get(qid, questions[qid])

    def run_score(row: dict) -> dict:
        return score_answer(row, get_effective_question(row["question_id"]))

    question_results: list[dict] = []

    if args.parallelism <= 1:
        for row in valid_rows:
            result = run_score(row)
            qid = result["question_id"]
            print(
                f"  {qid}: correct={result['answer_correct']}"
                f"  completeness={result['completeness_pct']}%"
                f"  recall={result['document_recall_pct']}%"
                f"  extra_docs={result['invalid_extra_docs']}"
            )
            question_results.append(result)
    else:
        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures = {
                executor.submit(run_score, row): row
                for row in valid_rows
            }
            for future in as_completed(futures):
                result = future.result()
                qid = result["question_id"]
                print(
                    f"  {qid}: correct={result['answer_correct']}"
                    f"  completeness={result['completeness_pct']}%"
                    f"  recall={result['document_recall_pct']}%"
                    f"  extra_docs={result['invalid_extra_docs']}"
                )
                question_results.append(result)

    # =========================================================================
    # Aggregate stats and write results
    # =========================================================================

    n = len(question_results)
    if n > 0:
        avg_correctness = sum(1 for r in question_results if r["answer_correct"]) / n * 100
        avg_completeness = sum(r["completeness_pct"] for r in question_results) / n
        avg_recall = sum(r["document_recall_pct"] for r in question_results) / n
        avg_extra_docs = sum(r["invalid_extra_docs"] for r in question_results) / n
    else:
        avg_correctness = 0.0
        avg_completeness = 0.0
        avg_recall = 0.0
        avg_extra_docs = 0.0

    aggregate_stats = {
        "total_questions": n,
        "skipped_rows": skip_count,
        "average_correctness_pct": round(avg_correctness, 2),
        "average_completeness_pct": round(avg_completeness, 2),
        "average_recall_pct": round(avg_recall, 2),
        "average_extra_docs": round(avg_extra_docs, 2),
    }

    results_output = {
        "updated_question_file": args.output_file,
        "questions": question_results,
        "aggregate_stats": aggregate_stats,
    }

    print(f"\nWriting results to {args.results_file}...")
    write_json_file(args.results_file, results_output)

    print(f"\nDone.")
    print(f"  Questions scored: {n}")
    print(f"  Skipped rows:     {skip_count}")
    print(f"  Avg correctness:  {aggregate_stats['average_correctness_pct']}%")
    print(f"  Avg completeness: {aggregate_stats['average_completeness_pct']}%")
    print(f"  Avg recall:       {aggregate_stats['average_recall_pct']}%")
    print(f"  Avg extra docs:   {aggregate_stats['average_extra_docs']}")


if __name__ == "__main__":
    main()
