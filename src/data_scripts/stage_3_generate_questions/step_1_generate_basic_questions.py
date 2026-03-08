"""Script for generating basic questions from documents."""

import argparse
import json
import os
import random

from src.llm import Message, get_llm
from src.paths import QUESTIONS_PATH
from src.prompts.basic_questions import BASIC_QUERY_VALIDATION, BASIC_QUERIES_PROMPT
from src.utils import (
    count_json_files,
    DocumentFieldError,
    extract_document_content,
    extract_json_from_response,
    load_json_file,
    select_random_file_hierarchical,
    sources_resolver,
)


def generate_question(
    doc_path: str,
    quiet: bool = False,
) -> tuple[bool, str, str | None, str | None, str | None]:
    """
    Generate a question for a document.

    Args:
        doc_path: Path to the document relative to SOURCES_DIR.
        quiet: If True, suppress LLM output.

    Returns:
        (success, message_or_question, dataset_doc_uuid, title, content) tuple.
        On success, message_or_question is the generated question.
        On failure, dataset_doc_uuid, title, and content are None.
    """
    full_path = sources_resolver.to_absolute(doc_path)

    # Load the document
    try:
        doc_data = load_json_file(full_path)
    except Exception as e:
        return (False, f"Error loading document: {e}", None, None, None)

    # Get the UUID
    dataset_doc_uuid = doc_data.get("dataset_doc_uuid")
    if not dataset_doc_uuid:
        return (False, "Document missing 'dataset_doc_uuid'", None, None, None)

    # Extract title and content
    try:
        title, content = extract_document_content(doc_data)
    except DocumentFieldError as e:
        return (False, str(e), None, None, None)

    # Build the prompt
    prompt = BASIC_QUERIES_PROMPT.format(
        document_title=title,
        document_contents=content,
    )

    # Generate the question
    llm = get_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    question = response.strip()

    if not question:
        return (False, "LLM returned empty response", None, None, None)

    return (True, question, dataset_doc_uuid, title, content)


def append_to_jsonl(path: str, data: dict) -> None:
    """Append a JSON object to a JSONL file."""
    with open(path, "a") as f:
        f.write(json.dumps(data) + "\n")


def validate_question(
    title: str,
    content: str,
    question: str,
    quiet: bool = False,
) -> tuple[bool, str | None]:
    """
    Validate a question against its source document.

    Args:
        title: Document title.
        content: Document content.
        question: Generated question to validate.
        quiet: If True, suppress LLM output.

    Returns:
        (valid, expected_answer_explanation) tuple.
        On failure, expected_answer_explanation is None.
    """
    prompt = BASIC_QUERY_VALIDATION.format(
        document_title=title,
        document_contents=content,
        query=question,
    )

    llm = get_llm(tools=None, quiet=quiet)
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

    # Try to parse JSON
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        try:
            response = extract_json_from_response(response)
            data = json.loads(response)
        except Exception:
            return (False, None)

    # Check if valid
    is_valid = data.get("valid", False)
    if not is_valid:
        return (False, None)

    explanation = data.get("expected_answer_explanation")
    if not explanation or explanation == "N/A":
        return (False, None)

    return (True, explanation)


def count_existing_questions() -> int:
    """Count existing questions in the questions.jsonl file."""
    if not os.path.exists(QUESTIONS_PATH):
        return 0

    count = 0
    with open(QUESTIONS_PATH) as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def get_next_question_id() -> int:
    """Get the next question ID number based on existing questions."""
    if not os.path.exists(QUESTIONS_PATH):
        return 1

    max_id = 0
    with open(QUESTIONS_PATH) as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    question_id = data.get("question_id", "")
                    if question_id.startswith("qst_"):
                        num = int(question_id.replace("qst_", ""))
                        max_id = max(max_id, num)
                except (json.JSONDecodeError, ValueError):
                    pass

    return max_id + 1


def get_existing_doc_uuids() -> set[str]:
    """Get set of document UUIDs already used in questions (from expected_doc_ids)."""
    uuids: set[str] = set()
    if not os.path.exists(QUESTIONS_PATH):
        return uuids

    with open(QUESTIONS_PATH) as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    # Handle new format with expected_doc_ids
                    if "expected_doc_ids" in data:
                        for doc_id in data["expected_doc_ids"]:
                            uuids.add(doc_id)
                    # Also handle old format for backwards compatibility
                    elif "dataset_doc_uuid" in data:
                        uuids.add(data["dataset_doc_uuid"])
                except json.JSONDecodeError:
                    pass

    return uuids


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate basic questions from documents."
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

    print("Step 1: Generate Basic Questions")
    print("=" * 40)
    print("This script generates questions from randomly sampled documents.")
    print("Each question should be fully answerable from a single document.")
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
    skip_count = 0
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
            # Check if we already have a question for this document
            full_path = sources_resolver.to_absolute(doc_path)
            try:
                doc_data = load_json_file(full_path)
                doc_uuid = doc_data.get("dataset_doc_uuid")
                if doc_uuid and doc_uuid not in existing_uuids:
                    break
            except Exception:
                pass

            # Try another document
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

        print("\n--- Generating Question ---")
        success, result, doc_uuid, title, content = generate_question(
            doc_path, quiet=args.quiet
        )

        if not success or not doc_uuid:
            fail_count += 1
            errors.append(f"{doc_path}: {result}")
            print(f"\nFailed: {result}")
            continue

        # Validate the question
        print("\n--- Validating Question ---")
        valid, explanation = validate_question(
            title, content, result, quiet=args.quiet
        )

        if not valid:
            fail_count += 1
            errors.append(f"{doc_path}: Question validation failed")
            print("\nFailed: Question validation failed")
            continue

        # Generate question ID
        question_id = f"qst_{next_question_id:04d}"

        # Append to questions file
        question_data = {
            "question_id": question_id,
            "question": result,
            "expected_doc_ids": [doc_uuid],
            "expected_answer_explanation": explanation,
            "question_type": "basic",
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
