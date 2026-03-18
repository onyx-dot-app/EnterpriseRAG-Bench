"""Script for generating constrained questions via corpus exploration."""

import argparse
import json
import os
import random

from src.llm import Message, get_llm, run_auto_conversation
from src.paths import GENERATED_DATA_DIR, QUESTIONS_PATH, SOURCE_TREE_PATH, SOURCES_DIR
from src.prompts.constrained_queries import (
    CONSTRAINED_QUERIES_ANSWER_VALIDATION_PROMPT,
    CONSTRAINED_QUERIES_ERROR_PROMPT,
    CONSTRAINED_QUERIES_SYSTEM_PROMPT,
    CONSTRAINED_QUERIES_USER_PROMPT,
)
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import (
    DocumentReadTool,
    FinishTool,
    GlobTool,
    GrepTool,
    LsTool,
)
from src.utils import (
    DocumentFieldError,
    count_existing_questions,
    extract_answer_facts,
    extract_document_content,
    extract_json_from_response,
    extract_source_type,
    get_next_question_id,
    load_file,
    load_json_file,
    save_question,
    write_json_file,
)

CACHE_DIR = "generation_cache"
CACHE_PATH = os.path.join(CACHE_DIR, "constrained_questions.json")


# =============================================================================
# Used Documents Cache
# =============================================================================


def load_used_document_paths() -> list[str]:
    """Load list of document paths already used in constrained questions."""
    if os.path.exists(CACHE_PATH):
        try:
            data = load_json_file(CACHE_PATH)
            return data.get("used_document_paths", [])
        except Exception:
            pass
    return []


def save_used_document_paths(paths: list[str]) -> None:
    """Save list of used document paths to cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    write_json_file(CACHE_PATH, {"used_document_paths": paths})


# =============================================================================
# Document Loading
# =============================================================================


def load_documents_by_paths(
    doc_paths: list[str],
) -> list[dict]:
    """Load documents from paths relative to GENERATED_DATA_DIR.

    Paths are expected to include the "sources/" prefix (e.g.,
    "sources/confluence/doc.json") as returned by the LLM tools.

    Returns list of dicts with keys: path, uuid, title, content.
    Skips documents that fail to load.
    """
    documents: list[dict] = []
    for rel_path in doc_paths:
        full_path = os.path.join(GENERATED_DATA_DIR, rel_path)
        try:
            doc_data = load_json_file(full_path)
            title, content = extract_document_content(doc_data)
            uuid = doc_data.get("dataset_doc_uuid", "")
            documents.append({
                "path": rel_path,
                "uuid": uuid,
                "title": title,
                "content": content,
            })
        except (Exception, DocumentFieldError) as e:
            print(f"  Warning: Failed to load {rel_path}: {e}")
    return documents


# =============================================================================
# Question Generation
# =============================================================================


def generate_constrained_question(
    source_tree: str,
    used_document_paths: list[str],
    quiet: bool = False,
) -> tuple[str | None, list[str] | None, list[str] | None]:
    """
    Generate a constrained question by letting the LLM explore the corpus.

    Args:
        source_tree: Source directory tree string.
        used_document_paths: Paths already used in previous questions
            (relative to GENERATED_DATA_DIR, e.g. "sources/confluence/...").
        quiet: If True, suppress LLM output.

    Returns:
        (query, gold_doc_paths, distractor_doc_paths) tuple.
        All None on failure.
    """
    # Set up tools
    # Use GENERATED_DATA_DIR as base so LLM paths like "sources/confluence/..."
    # resolve correctly (source tree shows paths with the "sources/" prefix).
    glob_tool = GlobTool(base_dir=GENERATED_DATA_DIR)
    grep_tool = GrepTool(base_dir=GENERATED_DATA_DIR)
    ls_tool = LsTool(base_dir=GENERATED_DATA_DIR)
    read_tool = DocumentReadTool(
        base_dir=GENERATED_DATA_DIR,
        generated_doc_contents=True,
    )
    finish_tool = FinishTool()

    tool_schemas = [
        glob_tool.schema,
        grep_tool.schema,
        ls_tool.schema,
        read_tool.schema,
        finish_tool.schema,
    ]

    tool_runner = ToolRunner()
    tool_runner.register(glob_tool)
    tool_runner.register(grep_tool)
    tool_runner.register(ls_tool)
    tool_runner.register(read_tool)
    tool_runner.register(finish_tool)

    # Format system prompt
    used_paths_str = "\n".join(used_document_paths) if used_document_paths else "None"
    system_prompt = CONSTRAINED_QUERIES_SYSTEM_PROMPT.format(
        source_tree_contents=source_tree,
        used_document_paths=used_paths_str,
    )

    llm = get_llm(tools=tool_schemas, reasoning_level="high", quiet=quiet)
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=CONSTRAINED_QUERIES_USER_PROMPT),
    ]

    try:
        run_auto_conversation(
            llm, tool_runner, messages, max_tool_cycles=30, quiet=quiet
        )
    except RuntimeError:
        pass

    # The LLM may present a proposal and wait for approval before calling
    # finish. If finish wasn't called, send an approval message and continue.
    if not finish_tool.finished:
        messages.append(Message(
            role="user",
            content="Approved. Please call the finish tool with the JSON output now.",
        ))
        try:
            run_auto_conversation(
                llm, tool_runner, messages, max_tool_cycles=5, quiet=quiet
            )
        except RuntimeError:
            pass

    if not finish_tool.finished or not finish_tool.finish_info:
        return (None, None, None)

    # Parse finish output
    try:
        data = json.loads(finish_tool.finish_info)
    except json.JSONDecodeError:
        try:
            extracted = extract_json_from_response(finish_tool.finish_info)
            data = json.loads(extracted)
        except Exception:
            # Retry with error prompt
            finish_tool.reset()
            messages.append(
                Message(role="user", content=CONSTRAINED_QUERIES_ERROR_PROMPT)
            )
            try:
                run_auto_conversation(
                    llm, tool_runner, messages, max_tool_cycles=5, quiet=quiet
                )
            except RuntimeError:
                pass

            if not finish_tool.finished or not finish_tool.finish_info:
                return (None, None, None)

            try:
                data = json.loads(finish_tool.finish_info)
            except Exception:
                return (None, None, None)

    query = data.get("query")
    gold_documents = data.get("gold_documents", [])
    distractor_documents = data.get("distractor_documents", [])

    if not query or not gold_documents:
        return (None, None, None)

    return (query, gold_documents, distractor_documents)


# =============================================================================
# Question Validation
# =============================================================================


def validate_constrained_question(
    question: str,
    all_documents: list[dict],
    quiet: bool = False,
) -> tuple[bool, str | None, list[str] | None, list[str] | None]:
    """
    Validate a constrained question and generate a gold answer.

    Args:
        question: The generated question.
        all_documents: All documents (gold + distractor) in order.
            Each dict has keys: path, uuid, title, content.
        quiet: If True, suppress LLM output.

    Returns:
        (success, gold_answer, distractor_explanations, relevant_doc_uuids) tuple.
        On failure, all values after success are None.
    """
    if not all_documents:
        return (False, None, None, None)

    # Build numbered document contents
    parts: list[str] = []
    for i, doc in enumerate(all_documents, 1):
        parts.append(f"### Document {i}\n```\n{doc['title']}\n{doc['content']}\n```")
    relevant_document_contents = "\n\n".join(parts)

    prompt = CONSTRAINED_QUERIES_ANSWER_VALIDATION_PROMPT.format(
        query=question,
        relevant_document_contents=relevant_document_contents,
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
            return (False, None, None, None)

    gold_answer = data.get("gold_answer")
    if not gold_answer or gold_answer == "N/A":
        return (False, None, None, None)

    distractor_explanations = data.get("distractor_explanations", [])

    # Map numerical document_ids back to UUIDs
    document_ids = data.get("document_ids", [])
    relevant_uuids: list[str] = []
    for doc_id in document_ids:
        idx = int(doc_id) - 1
        if 0 <= idx < len(all_documents):
            uuid = all_documents[idx].get("uuid")
            if uuid:
                relevant_uuids.append(uuid)

    if not relevant_uuids:
        return (False, None, None, None)

    return (True, gold_answer, distractor_explanations, relevant_uuids)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate constrained questions via corpus exploration."
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

    print("Step 5: Generate Constrained Questions")
    print("=" * 40)
    print("This script generates constrained questions by exploring the corpus.")
    print("Each question uses qualifiers to narrow the answer to a small set of documents.")
    print()

    if args.seed is not None:
        random.seed(args.seed)
        print(f"Random seed: {args.seed}")

    # Load source tree
    if not os.path.exists(SOURCE_TREE_PATH):
        print(f"Error: Source tree not found at {SOURCE_TREE_PATH}")
        return

    source_tree = load_file(SOURCE_TREE_PATH)

    # Load used document paths cache
    used_document_paths = load_used_document_paths()
    if used_document_paths:
        print(f"Loaded {len(used_document_paths)} previously used document paths.")

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
    print(f"Will generate {args.count} new question(s).")
    print()

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    for i in range(args.count):
        print("\n" + "-" * 40)
        print(f"Question {i + 1} of {args.count}")
        print("-" * 40)

        # Generate constrained question
        print("\n--- Exploring Corpus & Generating Question ---")
        query, gold_paths, distractor_paths = generate_constrained_question(
            source_tree, used_document_paths, quiet=args.quiet
        )

        if not query or not gold_paths:
            fail_count += 1
            errors.append("Question generation failed")
            print("\nFailed: Question generation failed")
            continue

        print(f"\nQuery: {query}")
        print(f"Gold documents: {gold_paths}")
        print(f"Distractor documents: {distractor_paths or []}")

        # Load all documents for validation
        print("\n--- Loading Documents ---")
        gold_docs = load_documents_by_paths(gold_paths)
        distractor_docs = load_documents_by_paths(distractor_paths or [])
        all_docs = gold_docs + distractor_docs

        if not gold_docs:
            fail_count += 1
            errors.append("Failed to load any gold documents")
            print("\nFailed: Failed to load any gold documents")
            continue

        # Validate the question
        print("\n--- Validating Question ---")
        valid, gold_answer, distractor_explanations, relevant_uuids = (
            validate_constrained_question(query, all_docs, quiet=args.quiet)
        )

        if not valid or not gold_answer or not relevant_uuids:
            fail_count += 1
            errors.append("Question validation failed")
            print("\nFailed: Question validation failed")
            continue

        # Extract answer facts
        print("\n--- Extracting Answer Facts ---")
        extracted_facts = extract_answer_facts(query, gold_answer, quiet=args.quiet)

        if not extracted_facts:
            fail_count += 1
            errors.append("Answer fact extraction failed")
            print("\nFailed: Answer fact extraction failed")
            continue

        # Combine extracted facts with distractor explanations
        answer_facts = extracted_facts + (distractor_explanations or [])

        # Derive source types from relevant UUIDs.
        # Paths are relative to GENERATED_DATA_DIR (e.g., "sources/confluence/..."),
        # so strip the "sources/" prefix before extracting the source type.
        source_types = sorted(set(
            extract_source_type(
                doc["path"].removeprefix("sources/").removeprefix("sources\\")
            )
            for doc in all_docs
            if doc.get("uuid") in relevant_uuids
        ))

        # Generate question ID
        question_id = f"qst_{next_question_id:04d}"

        # Append to questions file
        save_question(
            question_id=question_id,
            question=query,
            expected_doc_ids=relevant_uuids,
            source_types=source_types,
            gold_answer=gold_answer,
            answer_facts=answer_facts,
            question_type="constrained",
        )
        next_question_id += 1

        # Update used document paths cache
        all_paths = gold_paths + (distractor_paths or [])
        for p in all_paths:
            if p not in used_document_paths:
                used_document_paths.append(p)
        save_used_document_paths(used_document_paths)

        success_count += 1
        print(f"\nSaved question {question_id} (docs: {relevant_uuids})")

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
