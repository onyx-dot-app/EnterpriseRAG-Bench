"""Script for generating semantic questions from documents."""

import argparse
import os
import random

from src.paths import QUESTIONS_PATH
from src.prompts.basic_questions import SEMANTIC_QUERIES_PROMPT
from src.utils import (
    append_to_jsonl,
    count_existing_questions,
    count_json_files,
    extract_answer_facts,
    extract_source_type,
    generate_question,
    get_existing_doc_uuids,
    get_next_question_id,
    load_document,
    load_json_file,
    select_random_file_hierarchical,
    sources_resolver,
    validate_question,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate semantic questions from documents."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Number of questions to generate (default: 50)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    print("Step 2: Generate Semantic Questions")
    print("=" * 40)
    print("This script generates semantic questions from randomly sampled documents.")
    print("Semantic questions avoid strong lexical matches to test semantic retrieval.")
    print()

    if args.seed is not None:
        random.seed(args.seed)
        print(f"Random seed: {args.seed}")

    # Count JSON files
    total_files = count_json_files()

    if total_files == 0:
        print("No JSON files found in sources directory.")
        return

    # Check if questions file exists
    file_exists = os.path.exists(QUESTIONS_PATH)
    if file_exists:
        existing_questions = count_existing_questions()
        existing_uuids = get_existing_doc_uuids()
        next_question_id = get_next_question_id()
        print(f"Found existing questions file: {QUESTIONS_PATH}")
        print(f"  Existing questions: {existing_questions}")
        print(f"  Next question ID: qst_{next_question_id:04d}")
        print("  New questions will be appended to this file.")
    else:
        existing_questions = 0
        existing_uuids = set()
        next_question_id = 1
        print(f"Questions file not found. Will create: {QUESTIONS_PATH}")

    print()
    print(f"Found {total_files} JSON files in sources.")
    print(f"Will generate {args.count} new question(s).")
    print()

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    for i in range(args.count):
        print("\n" + "-" * 40)
        print(f"Question {i + 1} of {args.count}")
        print("-" * 40)

        # Select a random file using hierarchical random walk
        doc_path = select_random_file_hierarchical()

        if not doc_path:
            print("Failed to select a document")
            fail_count += 1
            errors.append("Failed to select a document")
            continue

        # Try to avoid selecting documents we already have questions for
        attempts = 0
        while attempts < 20:
            full_path = sources_resolver.to_absolute(doc_path)
            try:
                doc_data = load_json_file(full_path)
                doc_uuid = doc_data.get("dataset_doc_uuid")
                if doc_uuid and doc_uuid not in existing_uuids:
                    break
            except Exception:
                pass

            doc_path = select_random_file_hierarchical()
            attempts += 1
            if doc_path is None:
                break

        if doc_path is None:
            print("Failed to select a document")
            fail_count += 1
            errors.append("Failed to select a document")
            continue

        print(f"Document: {doc_path}")

        # Load document
        success, message, doc_uuid, title, content = load_document(doc_path)

        if not success or not doc_uuid:
            fail_count += 1
            errors.append(f"{doc_path}: {message}")
            print(f"\nFailed: {message}")
            continue

        # Generate question
        print("\n--- Generating Question ---")
        question = generate_question(
            title, content, SEMANTIC_QUERIES_PROMPT, quiet=args.quiet
        )

        if not question:
            fail_count += 1
            errors.append(f"{doc_path}: LLM returned empty response")
            print("\nFailed: LLM returned empty response")
            continue

        # Validate the question
        print("\n--- Validating Question ---")
        valid, gold_answer = validate_question(
            title, content, question, quiet=args.quiet
        )

        if not valid:
            fail_count += 1
            errors.append(f"{doc_path}: Question validation failed")
            print("\nFailed: Question validation failed")
            continue

        # Extract answer facts
        print("\n--- Extracting Answer Facts ---")
        answer_facts = extract_answer_facts(question, gold_answer, quiet=args.quiet)

        if not answer_facts:
            fail_count += 1
            errors.append(f"{doc_path}: Answer fact extraction failed")
            print("\nFailed: Answer fact extraction failed")
            continue

        # Generate question ID
        question_id = f"qst_{next_question_id:04d}"

        # Append to questions file
        question_data = {
            "question_id": question_id,
            "question": question,
            "expected_doc_ids": [doc_uuid],
            "source_types": [extract_source_type(doc_path)],
            "gold_answer": gold_answer,
            "answer_facts": answer_facts,
            "question_type": "semantic",
        }
        append_to_jsonl(QUESTIONS_PATH, question_data)
        existing_uuids.add(doc_uuid)
        next_question_id += 1

        success_count += 1
        print(f"\nSaved question {question_id} for {doc_uuid}")

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


if __name__ == "__main__":
    main()
