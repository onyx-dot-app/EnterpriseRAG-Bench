"""Script for generating metadata-related questions.

Samples random documents from the corpus and generates questions that require
metadata (e.g. dates, authors, categories) to be answered correctly. The metadata
may serve as a qualifier/scope or as the core of the query. Each question is
validated, a gold answer is produced, and answer facts are extracted.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_11_optional_metadata_questions [OPTIONS]

Args:
    --count  Number of questions to generate (default: 100)
    --quiet  Suppress LLM output streaming
"""

import argparse
import json
import os

from src.llm import Message, get_llm
from src.paths import EXTRA_QUESTIONS_PATH
from src.prompts.questions_metadata import (
    METADATA_DOCUMENT_ANSWER_GENERATION,
    METADATA_QUERIES_PROMPT,
)
from src.utils import (
    count_json_files,
    extract_answer_facts,
    extract_source_type,
    load_json_file,
    save_question,
    select_random_file_hierarchical,
    sources_resolver,
)
from src.utils.json_extraction import extract_json_from_response

STEP_OVERVIEW = """\
Generates questions requiring document metadata (dates, authors, categories) to
answer correctly. These sit outside the main benchmark since metadata handling
varies across systems. Written to a separate questions file.
"""


def _count_existing_questions(path: str) -> int:
    """Count existing questions in a JSONL file."""
    if not os.path.exists(path):
        return 0
    count = 0
    with open(path) as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _get_next_question_id(path: str) -> int:
    """Get the next question ID number from a JSONL file."""
    if not os.path.exists(path):
        return 1
    max_id = 0
    with open(path) as f:
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


def _get_existing_doc_uuids(path: str) -> set[str]:
    """Get set of document UUIDs already used in questions."""
    uuids: set[str] = set()
    if not os.path.exists(path):
        return uuids
    with open(path) as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    if "expected_doc_ids" in data:
                        for doc_id in data["expected_doc_ids"]:
                            uuids.add(doc_id)
                    elif "dataset_doc_uuid" in data:
                        uuids.add(data["dataset_doc_uuid"])
                except json.JSONDecodeError:
                    pass
    return uuids


def _generate_metadata_question(
    full_document_contents: str,
    quiet: bool = False,
) -> str | None:
    """Generate a metadata-related question for a document."""
    prompt = METADATA_QUERIES_PROMPT.format(
        full_document_contents=full_document_contents,
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

    question = response.strip()
    return question if question else None


def _validate_metadata_question(
    full_document_contents: str,
    question: str,
    quiet: bool = False,
) -> tuple[bool, str | None]:
    """Validate a metadata question and generate a gold answer."""
    prompt = METADATA_DOCUMENT_ANSWER_GENERATION.format(
        full_document_contents=full_document_contents,
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

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        try:
            response = extract_json_from_response(response)
            data = json.loads(response)
        except Exception:
            return (False, None)

    is_valid = data.get("valid", False)
    if not is_valid:
        return (False, None)

    gold_answer = data.get("gold_answer")
    if not gold_answer or gold_answer == "N/A":
        return (False, None)

    return (True, gold_answer)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate metadata-related questions from documents."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of questions to generate (default: 100)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    questions_path = EXTRA_QUESTIONS_PATH

    print("Step 11: Generate Metadata Questions (Optional)")
    print("=" * 40)
    print(STEP_OVERVIEW)
    print(f"Output file: {questions_path}")
    print()

    total_files = count_json_files()

    if total_files == 0:
        print("No JSON files found in sources directory.")
        return

    file_exists = os.path.exists(questions_path)
    if file_exists:
        existing_questions = _count_existing_questions(questions_path)
        existing_uuids = _get_existing_doc_uuids(questions_path)
        next_question_id = _get_next_question_id(questions_path)
        print(f"Found existing questions file: {questions_path}")
        print(f"  Existing questions: {existing_questions}")
        print(f"  Next question ID: qst_{next_question_id:04d}")
        print("  New questions will be appended to this file.")
    else:
        existing_questions = 0
        existing_uuids = set()
        next_question_id = 1
        print(f"Questions file not found. Will create: {questions_path}")

    print()
    print(f"Found {total_files} JSON files in sources.")
    print(f"Will generate {args.count} new question(s).")
    print()

    success_count = 0
    fail_count = 0
    errors: list[str] = []
    attempt_num = 0

    while success_count < args.count:
        attempt_num += 1
        print("\n" + "-" * 40)
        print(f"Question {success_count + 1} of {args.count} (attempt {attempt_num})")
        print("-" * 40)

        # Select a random file using hierarchical random walk
        doc_path = select_random_file_hierarchical()

        if not doc_path:
            print("Failed to select a document, retrying...")
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
            print("Failed to select a document, retrying...")
            fail_count += 1
            errors.append("Failed to select a document")
            continue

        print(f"Document: {doc_path}")

        # Load full document JSON (metadata prompts need the full document)
        full_path = sources_resolver.to_absolute(doc_path)
        try:
            doc_data = load_json_file(full_path)
        except Exception as e:
            fail_count += 1
            errors.append(f"{doc_path}: Error loading document: {e}")
            print(f"\nFailed: Error loading document: {e}, retrying...")
            continue

        doc_uuid = doc_data.get("dataset_doc_uuid")
        if not doc_uuid:
            fail_count += 1
            errors.append(f"{doc_path}: Document missing 'dataset_doc_uuid'")
            print("\nFailed: Document missing 'dataset_doc_uuid', retrying...")
            continue

        full_document_contents = json.dumps(doc_data, indent=2, ensure_ascii=False)

        # Generate question
        print("\n--- Generating Question ---")
        question = _generate_metadata_question(full_document_contents, quiet=args.quiet)

        if not question:
            fail_count += 1
            errors.append(f"{doc_path}: LLM returned empty response")
            print("\nFailed: LLM returned empty response, retrying...")
            continue

        # Validate the question
        print("\n--- Validating Question ---")
        valid, gold_answer = _validate_metadata_question(
            full_document_contents, question, quiet=args.quiet
        )

        if not valid or gold_answer is None:
            fail_count += 1
            errors.append(f"{doc_path}: Question validation failed")
            print("\nFailed: Question validation failed, retrying...")
            continue

        # Extract answer facts
        print("\n--- Extracting Answer Facts ---")
        answer_facts = extract_answer_facts(question, gold_answer, quiet=args.quiet)

        if not answer_facts:
            fail_count += 1
            errors.append(f"{doc_path}: Answer fact extraction failed")
            print("\nFailed: Answer fact extraction failed, retrying...")
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
            question_type="metadata",
            path=questions_path,
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
    print(f"Total questions in file: {_count_existing_questions(questions_path)}")

    if errors:
        print()
        print("Errors:")
        for error in errors[:20]:
            print(f"  - {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    print("\nMetadata question generation complete.")


if __name__ == "__main__":
    main()
