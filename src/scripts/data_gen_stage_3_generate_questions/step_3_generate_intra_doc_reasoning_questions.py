"""Script for generating intra-document reasoning questions.

Generates questions that require relating information from different parts of a single
long document. Pre-filters for documents meeting a minimum length threshold to ensure
intra-document reasoning is feasible. Validates that the question cannot be answered from
any single consecutive chunk of the document.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_3_generate_intra_doc_reasoning_questions [OPTIONS]

Args:
    --count           Number of questions to generate (default: 40)
    --min-doc-length  Minimum document content length in characters (default: 3000)
    --quiet           Suppress LLM output streaming
"""

import argparse
import os
import random

from src.paths import QUESTIONS_PATH
from src.prompts.answer_generation import INTRA_DOCUMENT_REASONING_ANSWER_GENERATION
from src.prompts.intra_document_reasoning import INTRA_DOCUMENT_REASONING_PROMPT
from src.utils import (
    collect_json_files_by_size,
    count_existing_questions,
    extract_answer_facts,
    extract_source_type,
    generate_question,
    get_existing_doc_uuids,
    get_next_question_id,
    is_noise_document,
    load_document,
    save_question,
    sources_resolver,
    validate_question,
)

STEP_OVERVIEW = """\
Generates questions that require relating information from different parts of a
single long document. Pre-filters for documents meeting a minimum length.
Validates that the question cannot be answered from any single consecutive chunk.
"""

# File size proxy threshold set below the char minimum to avoid false negatives.
# JSON overhead (keys, quotes, metadata) means file size > content length,
# so using 80% of the char minimum as byte threshold is conservative.
FILE_SIZE_PROXY_RATIO = 0.8


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate intra-document reasoning questions from documents."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=40,
        help="Number of questions to generate (default: 40)",
    )
    parser.add_argument(
        "--min-doc-length",
        type=int,
        default=3000,
        help="Minimum document content length in characters (default: 3000)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    print("Step 3: Generate Intra-Document Reasoning Questions")
    print("=" * 40)
    print(STEP_OVERVIEW)

    # Pre-scan for docs meeting minimum file size (proxy for content length)
    min_file_bytes = int(args.min_doc_length * FILE_SIZE_PROXY_RATIO)
    print(f"Minimum document content length: {args.min_doc_length} chars")
    print(f"Scanning for JSON files >= {min_file_bytes} bytes...")
    candidate_docs = collect_json_files_by_size(min_file_bytes)

    if not candidate_docs:
        print("No JSON files found meeting the minimum size requirement.")
        return

    print(f"Found {len(candidate_docs)} candidate documents.")

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
    print(f"Will generate {args.count} new question(s).")
    print()

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    for i in range(args.count):
        print("\n" + "-" * 40)
        print(f"Question {i + 1} of {args.count}")
        print("-" * 40)

        # Sample from candidate docs, trying to avoid already-used documents
        # and noise documents (near-duplicates / misc files).
        doc_path: str | None = None
        attempts = 0
        while attempts < 20:
            candidate = random.choice(candidate_docs)

            # Load and verify content length + uniqueness
            success, message, doc_uuid, title, content = load_document(candidate)
            full_path = sources_resolver.to_absolute(candidate)
            if (
                success
                and doc_uuid
                and doc_uuid not in existing_uuids
                and content
                and len(content) >= args.min_doc_length
                and not is_noise_document(full_path)
            ):
                doc_path = candidate
                break

            attempts += 1

        if doc_path is None or not doc_uuid or not title or not content:
            print("Failed to select a qualifying document")
            fail_count += 1
            errors.append("Failed to select a qualifying document")
            continue

        print(f"Document: {doc_path} ({len(content)} chars)")

        # Generate question
        print("\n--- Generating Question ---")
        question = generate_question(
            title, content, INTRA_DOCUMENT_REASONING_PROMPT, quiet=args.quiet
        )

        if not question:
            fail_count += 1
            errors.append(f"{doc_path}: LLM returned empty response")
            print("\nFailed: LLM returned empty response")
            continue

        # Validate the question
        print("\n--- Validating Question ---")
        valid, gold_answer = validate_question(
            title,
            content,
            question,
            quiet=args.quiet,
            answer_prompt_template=INTRA_DOCUMENT_REASONING_ANSWER_GENERATION,
        )

        if not valid or gold_answer is None:
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
        save_question(
            question_id=question_id,
            question=question,
            expected_doc_ids=[doc_uuid],
            source_types=[extract_source_type(doc_path)],
            gold_answer=gold_answer,
            answer_facts=answer_facts,
            question_type="intra_document_reasoning",
        )
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

    print(
        "\nThis step is complete, go on to step 4 to generate project-related questions."
    )


if __name__ == "__main__":
    main()
