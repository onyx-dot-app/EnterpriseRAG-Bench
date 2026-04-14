"""Script for generating conflicting/outdated information questions from document pairs.

Uses near-duplicate document pairs from the duplications cache (Stage 2 Step 4) to
generate questions that test a system's ability to reconcile conflicting information.
Typically one document supersedes the other, requiring the answer to identify the most
current facts.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_6_generate_conflicting_questions [OPTIONS]

Args:
    --count        Max number of questions to process (default: 20)
    --parallelism  Number of parallel workers (default: 1)
    --quiet        Suppress LLM output streaming
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llm import Message, get_llm
from src.paths import QUESTIONS_PATH
from src.prompts.conflicting_query import CONFLICTING_INFO_PROMPT
from src.utils import (
    count_existing_questions,
    duplications_cache,
    ensure_uuids_resolved,
    extract_json_from_response,
    extract_source_type,
    get_next_question_id,
    load_document_content_by_uuid,
    save_question,
)
from src.utils.document_content import DocumentFieldError

STEP_OVERVIEW = """\
Uses near-duplicate document pairs from Stage 2 Step 4 to generate questions
where information conflicts. Typically one document supersedes the other, testing
whether the system identifies the most current facts.
"""


# =============================================================================
# Loading
# =============================================================================


def load_duplication_entries() -> list[dict]:
    """Load all duplication entries from generation cache."""
    return duplications_cache.load()


# =============================================================================
# Document Formatting
# =============================================================================


def format_document(uuid: str, uuid_index: dict[str, str]) -> str | None:
    """Format a single document for the prompt. Returns None on failure."""
    if uuid not in uuid_index:
        return None
    try:
        title, content = load_document_content_by_uuid(uuid, uuid_index)
    except (DocumentFieldError, Exception):
        return None
    return f"Document ID: {uuid}\n```\n{title}\n{content}\n```"


# =============================================================================
# Single Question Processing
# =============================================================================


def process_single_entry(
    entry: dict,
    uuid_index: dict[str, str],
    quiet: bool = False,
) -> tuple[bool, str, dict | None]:
    """
    Process a single duplication entry end-to-end.

    The LLM generates the query, gold answer, and verifiable statements
    (used as answer_facts) in a single call.

    Returns:
        (success, message, question_data) tuple.
        On failure, question_data is None.
    """
    entry_label = (
        f"{entry.get('document_old', '?')[:16]}..{entry.get('document_new', '?')[:16]}"
    )
    old_uuid = entry.get("document_old", "")
    new_uuid = entry.get("document_new", "")

    if not old_uuid or not new_uuid:
        return (False, f"{entry_label}: Missing document_old or document_new", None)

    # Format both documents
    if not quiet:
        print("\n--- Loading Documents ---")

    doc_old_text = format_document(old_uuid, uuid_index)
    if not doc_old_text:
        return (False, f"{entry_label}: Could not load document_old ({old_uuid})", None)

    doc_new_text = format_document(new_uuid, uuid_index)
    if not doc_new_text:
        return (False, f"{entry_label}: Could not load document_new ({new_uuid})", None)

    if not quiet:
        print(f"Loaded document_old: {old_uuid}")
        print(f"Loaded document_new: {new_uuid}")

    # Generate question, answer, and facts in one LLM call
    if not quiet:
        print("\n--- Generating Conflicting Question ---")

    prompt = CONFLICTING_INFO_PROMPT.format(
        document_1=doc_old_text,
        document_2=doc_new_text,
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
            return (False, f"{entry_label}: Failed to parse LLM JSON response", None)

    if not isinstance(data, dict):
        return (False, f"{entry_label}: LLM response is not a JSON object", None)

    query = data.get("query", "").strip()
    gold_answer = data.get("gold_answer", "").strip()
    answer_facts = data.get("verifiable_statements", [])

    if not query:
        return (False, f"{entry_label}: LLM returned empty query", None)

    if not gold_answer:
        return (False, f"{entry_label}: LLM returned empty gold_answer", None)

    if not answer_facts or not isinstance(answer_facts, list):
        return (False, f"{entry_label}: LLM returned no verifiable_statements", None)

    if not quiet:
        print(f"\nQuery: {query}")
        print(f"Gold answer: {gold_answer[:200]}...")
        print(f"Verifiable statements: {len(answer_facts)}")

    # Both documents are expected
    expected_doc_ids = [old_uuid, new_uuid]

    source_types = sorted(
        set(
            extract_source_type(uuid_index[uuid])
            for uuid in expected_doc_ids
            if uuid in uuid_index
        )
    )

    question_data = {
        "question": query,
        "expected_doc_ids": expected_doc_ids,
        "source_types": source_types,
        "gold_answer": gold_answer,
        "answer_facts": answer_facts,
        "question_type": "conflicting_info",
    }

    return (True, f"{entry_label}: Success", question_data)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate conflicting/outdated information questions from document pairs."
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

    print("Step 6: Generate Conflicting Questions")
    print("=" * 40)
    print(STEP_OVERVIEW)

    # Load duplication entries
    entries = load_duplication_entries()
    if not entries:
        print("No duplication entries found in generation cache.")
        print("Run Stage 2 Step 4 first (step_4_generate_near_duplicates).")
        return
    print(f"Loaded {len(entries)} duplication entries from generation cache.")

    # Limit count
    if args.count is not None:
        entries = entries[: args.count]
        print(f"Processing {len(entries)} entries (limited by --count).")

    # Load UUID index, rebuilding if needed UUIDs are missing
    needed_uuids = set()
    for entry in entries:
        needed_uuids.add(entry.get("document_old", ""))
        needed_uuids.add(entry.get("document_new", ""))
    needed_uuids.discard("")

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
        f"Processing {len(entries)} duplication entries with parallelism={args.parallelism}."
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
            print(f"  Old: {entry.get('document_old', '?')}")
            print(f"  New: {entry.get('document_new', '?')}")
            print("-" * 40)

            success, message, question_data = process_single_entry(
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
        # Parallel mode — quiet workers, collect results
        results: list[tuple[int, bool, str, dict | None]] = []

        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures = {
                executor.submit(
                    process_single_entry,
                    entry,
                    uuid_index,
                    True,  # quiet=True for parallel workers
                ): idx
                for idx, entry in enumerate(entries)
            }

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    success, message, question_data = future.result()
                    results.append((idx, success, message, question_data))
                    status = "OK" if success else "FAIL"
                    print(f"  [{idx + 1}/{len(entries)}] {status}: {message}")
                except Exception as e:
                    results.append((idx, False, str(e), None))
                    print(f"  [{idx + 1}/{len(entries)}] ERROR: {e}")

        # Save results in original order to keep question IDs deterministic
        results.sort(key=lambda r: r[0])

        for idx, success, message, question_data in results:
            if not success or not question_data:
                fail_count += 1
                errors.append(message)
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
        "\nThis step is complete, go on to step 7 to generate completeness questions."
    )


if __name__ == "__main__":
    main()
