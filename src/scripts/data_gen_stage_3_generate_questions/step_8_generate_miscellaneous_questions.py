"""Script for generating questions from miscellaneous noise documents.

Generates questions from the informal, off-topic documents created in Stage 2 Step 3
(e.g. files in slack/memes or google_drive/.../misc-assets). These documents sit outside
the main scaffolding and present a retrieval challenge due to their peripheral topics and
unpredictable locations.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_8_generate_miscellaneous_questions [OPTIONS]

Args:
    --count        Number of questions to generate (default: 20)
    --parallelism  Number of parallel workers (default: 1)
    --quiet        Suppress LLM output streaming
"""

import argparse
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.paths import QUESTIONS_PATH
from src.prompts.basic_questions import BASIC_QUERIES_PROMPT
from src.utils import (
    count_existing_questions,
    ensure_uuids_resolved,
    extract_answer_facts,
    extract_source_type,
    generate_question,
    get_next_question_id,
    load_document_content_by_uuid,
    misc_files_cache,
    save_question,
    validate_question,
)
from src.utils.document_content import DocumentFieldError

STEP_OVERVIEW = """\
Generates questions from the informal, off-topic documents created in Stage 2
Step 3. These peripheral documents sit outside the main scaffolding and are
stored in less predictable locations, creating a retrieval challenge.
"""


# =============================================================================
# Single Question Processing
# =============================================================================


def process_single_question(
    doc_uuid: str,
    uuid_index: dict[str, str],
    quiet: bool = False,
) -> tuple[bool, str, dict | None]:
    """
    Process a single miscellaneous document into a question end-to-end.

    Returns:
        (success, message, question_data) tuple.
        On failure, question_data is None.
    """
    if doc_uuid not in uuid_index:
        return (False, f"{doc_uuid}: Not found in UUID index", None)

    doc_path = uuid_index[doc_uuid]

    # Load document content
    try:
        title, content = load_document_content_by_uuid(doc_uuid, uuid_index)
    except (DocumentFieldError, Exception) as e:
        return (False, f"{doc_uuid}: Failed to load document: {e}", None)

    # Generate question
    if not quiet:
        print("\n--- Generating Question ---")

    question = generate_question(title, content, BASIC_QUERIES_PROMPT, quiet=quiet)

    if not question:
        return (False, f"{doc_uuid}: LLM returned empty question", None)

    if not quiet:
        print(f"\nQuestion: {question}")

    # Validate and get gold answer
    if not quiet:
        print("\n--- Validating Question ---")

    valid, gold_answer = validate_question(title, content, question, quiet=quiet)

    if not valid or not gold_answer:
        return (False, f"{doc_uuid}: Question validation failed", None)

    # Extract answer facts
    if not quiet:
        print("\n--- Extracting Answer Facts ---")

    answer_facts = extract_answer_facts(question, gold_answer, quiet=quiet)

    if not answer_facts:
        return (False, f"{doc_uuid}: Answer fact extraction failed", None)

    source_types = [extract_source_type(doc_path)]

    question_data = {
        "question": question,
        "expected_doc_ids": [doc_uuid],
        "source_types": source_types,
        "gold_answer": gold_answer,
        "answer_facts": answer_facts,
        "question_type": "miscellaneous",
    }

    return (True, f"{doc_uuid}: Success", question_data)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate questions from miscellaneous noise documents."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of questions to generate (default: 20)",
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

    print("Step 8: Generate Miscellaneous Questions")
    print("=" * 40)
    print(STEP_OVERVIEW)
    print()

    # Load misc file UUIDs from generation cache
    file_uuids = misc_files_cache.load()
    if not file_uuids:
        print("No misc file entries found in generation cache.")
        print("Run Stage 2 Step 3 first (step_3_generate_misc_files).")
        return
    print(f"Found {len(file_uuids)} misc file(s) in generation cache.")

    # Load UUID index, rebuilding if needed UUIDs are missing
    uuid_index = ensure_uuids_resolved(set(file_uuids))
    print(f"UUID index has {len(uuid_index)} entries.")

    # Filter to resolvable UUIDs (may still have gaps after rebuild)
    resolvable = [uid for uid in file_uuids if uid in uuid_index]
    if len(resolvable) < len(file_uuids):
        print(
            f"  {len(file_uuids) - len(resolvable)} UUID(s) not resolvable, skipping them."
        )
    if not resolvable:
        print("No resolvable misc file UUIDs. Nothing to do.")
        return

    # Determine count (capped to available documents)
    count = len(resolvable) if args.count is None else min(args.count, len(resolvable))
    if args.count is not None and args.count > len(resolvable):
        print(
            f"  Requested {args.count} but only {len(resolvable)} documents available. Using {count}."
        )

    # Shuffle and select
    selected = resolvable[:count]
    if args.count is not None:
        random.shuffle(resolvable)
        selected = resolvable[:count]

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
    print(f"Processing {count} document(s) with parallelism={args.parallelism}.")
    print()

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    if args.parallelism <= 1:
        # Sequential mode — verbose output
        for i, doc_uuid in enumerate(selected):
            print("\n" + "-" * 40)
            print(f"Document {i + 1} of {count}: {doc_uuid}")
            print(f"  Path: {uuid_index.get(doc_uuid, '?')}")
            print("-" * 40)

            success, message, question_data = process_single_question(
                doc_uuid, uuid_index, quiet=args.quiet
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
                    doc_uuid,
                    uuid_index,
                    True,  # quiet=True for parallel workers
                ): idx
                for idx, doc_uuid in enumerate(selected)
            }

            for future in as_completed(futures):
                idx = futures[future]
                completed += 1
                try:
                    success, message, question_data = future.result()
                except Exception as e:
                    fail_count += 1
                    errors.append(str(e))
                    print(f"  [{completed}/{count}] ERROR: {e}")
                    continue

                if not success or not question_data:
                    fail_count += 1
                    errors.append(message)
                    print(f"  [{completed}/{count}] FAIL: {message}")
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
                print(f"  [{completed}/{count}] OK: {message} -> {question_id}")

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

    print("\nThis step is complete, go on to step 9 to generate high-level questions.")


if __name__ == "__main__":
    main()
