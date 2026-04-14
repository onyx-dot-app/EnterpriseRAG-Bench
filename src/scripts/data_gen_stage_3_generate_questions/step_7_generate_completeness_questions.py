"""Script for generating completeness questions from cached completeness entries.

Processes completeness document clusters from Stage 1 Step 8 into questions that require
exhaustive retrieval of all relevant documents. For each cluster, an LLM filters out
unnecessary documents, generates a gold answer from the required set, and extracts
verifiable facts. Questions needing fewer than two documents are discarded.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_7_generate_completeness_questions [OPTIONS]

Args:
    --count        Max number of questions to process (default: 20)
    --parallelism  Number of parallel workers (default: 1)
    --quiet        Suppress LLM output streaming
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llm import Message, get_llm
from src.paths import QUESTIONS_PATH
from src.prompts.completeness_questions import (
    COMPLETENESS_ANSWER_GENERATION_PROMPT,
    COMPLETENESS_DOC_EVALUATION_PROMPT,
)
from src.utils import (
    completeness_cache,
    count_existing_questions,
    ensure_uuids_resolved,
    extract_answer_facts,
    extract_json_from_response,
    extract_source_type,
    get_next_question_id,
    load_document_content_by_uuid,
    save_question,
)
from src.utils.document_content import DocumentFieldError

STEP_OVERVIEW = """\
Processes completeness document clusters from Stage 1 Step 8 into questions
requiring exhaustive retrieval. For each cluster, unnecessary documents are
filtered, a gold answer is generated, and verifiable facts are extracted.
Questions needing fewer than two documents are discarded.
"""


# =============================================================================
# Loading
# =============================================================================


def load_completeness_entries() -> list[dict]:
    """Load all completeness entries from generation cache."""
    return completeness_cache.load()


# =============================================================================
# Document Formatting
# =============================================================================


def format_candidate_documents(
    doc_uuids: list[str],
    uuid_index: dict[str, str],
) -> tuple[str, list[str]]:
    """
    Format candidate documents for the evaluation prompt.

    Returns:
        (formatted_text, valid_uuids) — the formatted string and list of
        UUIDs that were successfully loaded.
    """
    parts: list[str] = []
    valid_uuids: list[str] = []

    for uuid in doc_uuids:
        if uuid not in uuid_index:
            continue
        try:
            title, content = load_document_content_by_uuid(uuid, uuid_index)
        except (DocumentFieldError, Exception):
            continue

        parts.append(f"Document ID: {uuid}\n```\n{title}\n{content}\n```")
        valid_uuids.append(uuid)

    return "\n\n".join(parts), valid_uuids


# =============================================================================
# Document Evaluation
# =============================================================================


def evaluate_required_documents(
    question: str,
    candidate_documents_text: str,
    valid_uuids: list[str],
    quiet: bool = False,
) -> list[str] | None:
    """
    Evaluate which candidate documents are required to answer the question.

    Returns:
        List of required document UUIDs, or None on failure.
    """
    prompt = COMPLETENESS_DOC_EVALUATION_PROMPT.format(
        query=question,
        candidate_documents=candidate_documents_text,
    )

    llm = get_llm(tools=None, reasoning_level="high", quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    response = response.strip()

    # Parse JSON response
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        try:
            response = extract_json_from_response(response)
            data = json.loads(response)
        except Exception:
            return None

    if not isinstance(data, dict):
        return None

    required_uuids: list[str] = []
    for uuid in valid_uuids:
        entry = data.get(uuid)
        if isinstance(entry, dict) and entry.get("classification") == "required":
            required_uuids.append(uuid)

    return required_uuids if required_uuids else None


# =============================================================================
# Answer Generation
# =============================================================================


def generate_completeness_answer(
    question: str,
    required_uuids: list[str],
    uuid_index: dict[str, str],
    quiet: bool = False,
) -> tuple[bool, str | None]:
    """
    Generate a gold answer from the required documents.

    The prompt returns the gold answer as plain text (not JSON).

    Returns:
        (valid, gold_answer) tuple.
    """
    parts: list[str] = []
    for uuid in required_uuids:
        try:
            title, content = load_document_content_by_uuid(uuid, uuid_index)
        except Exception:
            continue
        parts.append(f"Document ID: {uuid}\n```\n{title}\n{content}\n```")

    if not parts:
        return (False, None)

    relevant_documents_text = "\n\n".join(parts)

    prompt = COMPLETENESS_ANSWER_GENERATION_PROMPT.format(
        query=question,
        relevant_documents=relevant_documents_text,
    )

    llm = get_llm(tools=None, reasoning_level="high", quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    gold_answer = response.strip()
    if not gold_answer:
        return (False, None)

    return (True, gold_answer)


# =============================================================================
# Single Question Processing
# =============================================================================


def process_single_question(
    entry: dict,
    uuid_index: dict[str, str],
    quiet: bool = False,
) -> tuple[bool, str, dict | None]:
    """
    Process a single completeness question entry end-to-end.

    Returns:
        (success, message, question_data) tuple.
        On failure, question_data is None.
    """
    entry_label = entry.get("question", "unknown")[:60]
    question = entry.get("question", "")
    doc_uuids = entry.get("documents", [])

    if not question:
        return (False, f"{entry_label}: Missing question", None)

    if len(doc_uuids) < 2:
        return (
            False,
            f"{entry_label}: Need at least 2 documents, got {len(doc_uuids)}",
            None,
        )

    # Format candidate documents
    if not quiet:
        print("\n--- Formatting Candidate Documents ---")

    candidate_text, valid_uuids = format_candidate_documents(doc_uuids, uuid_index)

    if len(valid_uuids) < 2:
        return (
            False,
            f"{entry_label}: Only {len(valid_uuids)} resolvable documents (need >= 2)",
            None,
        )

    if not quiet:
        print(f"Loaded {len(valid_uuids)} of {len(doc_uuids)} documents")

    # Evaluate which documents are required
    if not quiet:
        print("\n--- Evaluating Required Documents ---")

    required_uuids = evaluate_required_documents(
        question, candidate_text, valid_uuids, quiet=quiet
    )

    if not required_uuids:
        return (
            False,
            f"{entry_label}: Document evaluation failed or no required docs",
            None,
        )

    if not quiet:
        print(f"\nRequired documents: {len(required_uuids)} of {len(valid_uuids)}")
        for uuid in required_uuids:
            print(f"  - {uuid}")

    # Generate gold answer
    if not quiet:
        print("\n--- Generating Gold Answer ---")

    valid, gold_answer = generate_completeness_answer(
        question, required_uuids, uuid_index, quiet=quiet
    )

    if not valid or not gold_answer:
        return (False, f"{entry_label}: Answer generation failed", None)

    if not quiet:
        print(f"\nGold answer: {gold_answer[:200]}...")

    # Extract answer facts
    if not quiet:
        print("\n--- Extracting Answer Facts ---")

    answer_facts = extract_answer_facts(question, gold_answer, quiet=quiet)

    if not answer_facts:
        return (False, f"{entry_label}: Answer fact extraction failed", None)

    if not quiet:
        print(f"\nExtracted {len(answer_facts)} facts")

    # Derive source types from required UUIDs
    source_types = sorted(
        set(
            extract_source_type(uuid_index[uuid])
            for uuid in required_uuids
            if uuid in uuid_index
        )
    )

    question_data = {
        "question": question,
        "expected_doc_ids": required_uuids,
        "source_types": source_types,
        "gold_answer": gold_answer,
        "answer_facts": answer_facts,
        "question_type": "completeness",
    }

    return (True, f"{entry_label}: Success", question_data)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate completeness questions from cached completeness entries."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Max number of questions to process (default: 20)",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1, verbose output)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    print("Step 7: Generate Completeness Questions")
    print("=" * 40)
    print(STEP_OVERVIEW)
    print()

    # Load completeness entries
    entries = load_completeness_entries()
    if not entries:
        print("No completeness entries found in generation cache.")
        print("Run Stage 1 Step 8 first (step_8_generate_completeness_documents).")
        return
    print(f"Loaded {len(entries)} completeness entries from generation cache.")

    # Limit count
    if args.count is not None:
        entries = entries[: args.count]
        print(f"Processing {len(entries)} entries (limited by --count).")

    # Load UUID index, rebuilding if needed UUIDs are missing
    needed_uuids: set[str] = set()
    for entry in entries:
        needed_uuids.update(entry.get("documents", []))

    uuid_index = ensure_uuids_resolved(needed_uuids)
    print(f"UUID index has {len(uuid_index)} entries.")

    # Load existing question state
    next_question_id = get_next_question_id()
    existing_questions = count_existing_questions()

    if existing_questions > 0:
        print(f"Found existing questions file: {QUESTIONS_PATH}")
        print(f"  Existing questions: {existing_questions}")
        print(f"  Next question ID: qst_{next_question_id:04d}")
        print("  New questions will be appended to this file.")
    else:
        print(f"Questions file not found. Will create: {QUESTIONS_PATH}")

    print()
    print(
        f"Processing {len(entries)} completeness entries with parallelism={args.parallelism}."
    )
    print()

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    if args.parallelism <= 1:
        # Sequential mode — verbose output
        for i, entry in enumerate(entries):
            print("\n" + "-" * 40)
            print(f"Entry {i + 1} of {len(entries)}")
            print(f"Question: {entry.get('question', '?')}")
            print("-" * 40)

            success, message, question_data = process_single_question(
                entry, uuid_index, quiet=args.quiet
            )

            if not success or not question_data:
                fail_count += 1
                errors.append(message)
                print(f"\nFailed: {message}")
                continue

            # Assign question ID and save
            question_id = f"qst_{next_question_id:04d}"
            save_question(
                question_id=question_id,
                question=question_data["question"],
                expected_doc_ids=question_data["expected_doc_ids"],
                source_types=question_data["source_types"],
                gold_answer=question_data["gold_answer"],
                answer_facts=question_data["answer_facts"],
                question_type=question_data["question_type"],
            )
            next_question_id += 1
            success_count += 1
            print(f"\nSaved question {question_id}")
    else:
        # Parallel mode — quiet workers, save incrementally as they complete
        completed = 0

        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures = {
                executor.submit(
                    process_single_question,
                    entry,
                    uuid_index,
                    True,  # quiet=True for parallel workers
                ): idx
                for idx, entry in enumerate(entries)
            }

            for future in as_completed(futures):
                idx = futures[future]
                completed += 1
                try:
                    success, message, question_data = future.result()
                except Exception as e:
                    fail_count += 1
                    errors.append(str(e))
                    print(f"  [{completed}/{len(entries)}] ERROR: {e}")
                    continue

                if not success or not question_data:
                    fail_count += 1
                    errors.append(message)
                    print(f"  [{completed}/{len(entries)}] FAIL: {message}")
                    continue

                question_id = f"qst_{next_question_id:04d}"
                save_question(
                    question_id=question_id,
                    question=question_data["question"],
                    expected_doc_ids=question_data["expected_doc_ids"],
                    source_types=question_data["source_types"],
                    gold_answer=question_data["gold_answer"],
                    answer_facts=question_data["answer_facts"],
                    question_type=question_data["question_type"],
                )
                next_question_id += 1
                success_count += 1
                print(f"  [{completed}/{len(entries)}] OK: {message} -> {question_id}")

    print("\n" + "=" * 40)
    print("Summary")
    print("=" * 40)
    print(f"Successfully generated: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Total questions in file: {count_existing_questions()}")

    if errors:
        print()
        print("Errors:")
        for error in errors[:20]:
            print(f"  - {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    print(
        "\nThis step is complete, go on to step 8 to generate miscellaneous questions."
    )


if __name__ == "__main__":
    main()
