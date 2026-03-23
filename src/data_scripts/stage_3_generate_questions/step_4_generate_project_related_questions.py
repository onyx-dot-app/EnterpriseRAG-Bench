"""Script for generating project-related cross-document questions."""

import argparse
import json
import os

from src.llm import Message, get_llm, run_auto_conversation
from src.paths import QUESTIONS_PATH, SOURCES_DIR
from src.prompts.project_question import (
    PROJECT_RELATED_QUERIES_ANSWER_VALIDATION_PROMPT,
    PROJECT_RELATED_QUERIES_PROMPT,
)
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import DocumentReadTool
from src.utils import (
    count_existing_questions,
    ensure_uuids_resolved,
    extract_answer_facts,
    extract_json_from_response,
    extract_source_type,
    get_next_question_id,
    load_json_file,
    projects_cache,
    save_question,
    write_json_file,
)

CACHE_DIR = "generation_cache"
PROJECT_USAGE_PATH = os.path.join(CACHE_DIR, "project_questions.json")


# =============================================================================
# Project Loading
# =============================================================================


def load_projects() -> list[dict]:
    """Load all project entries from generation cache."""
    return projects_cache.load()


def select_next_project(
    projects: list[dict],
    project_usage: dict[str, int],
) -> dict:
    """Select the project with the lowest usage count."""
    return min(
        projects,
        key=lambda p: (
            project_usage.get(p["project_outline_file"], 0),
            p["project_outline_file"],
        ),
    )


# =============================================================================
# Project Usage Cache
# =============================================================================


def load_project_usage() -> dict[str, int]:
    """Load project usage counts from generation cache."""
    if os.path.exists(PROJECT_USAGE_PATH):
        try:
            data = load_json_file(PROJECT_USAGE_PATH)
            return data.get("project_usage", {})
        except Exception:
            pass
    return {}


def save_project_usage(usage: dict[str, int]) -> None:
    """Save project usage counts to generation cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    write_json_file(PROJECT_USAGE_PATH, {"project_usage": usage})


# =============================================================================
# Question Validation
# =============================================================================


def validate_project_question(
    question: str,
    read_documents: list[dict],
    quiet: bool = False,
) -> tuple[bool, str | None, list[str] | None]:
    """
    Validate a project-related question and generate a gold answer.

    Args:
        question: The generated question.
        read_documents: Documents read during generation. Each dict has
            keys: path, uuid, title, content.
        quiet: If True, suppress LLM output.

    Returns:
        (success, gold_answer, relevant_doc_uuids) tuple.
        On failure, gold_answer and relevant_doc_uuids are None.
    """
    if not read_documents:
        return (False, None, None)

    # Build numbered document contents
    parts: list[str] = []
    for i, doc in enumerate(read_documents, 1):
        parts.append(f"### Document {i}\n```\n{doc['title']}\n{doc['content']}\n```")
    project_document_contents = "\n\n".join(parts)

    prompt = PROJECT_RELATED_QUERIES_ANSWER_VALIDATION_PROMPT.format(
        query=question,
        project_document_contents=project_document_contents,
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
            return (False, None, None)

    gold_answer = data.get("gold_answer")
    if not gold_answer or gold_answer == "N/A":
        return (False, None, None)

    # Map numerical document_ids back to UUIDs
    document_ids = data.get("document_ids", [])
    relevant_uuids: list[str] = []
    for doc_id in document_ids:
        idx = int(doc_id) - 1  # 1-indexed to 0-indexed
        if 0 <= idx < len(read_documents):
            uuid = read_documents[idx].get("uuid")
            if uuid:
                relevant_uuids.append(uuid)

    if not relevant_uuids:
        # Fall back to all read document UUIDs
        relevant_uuids = [d["uuid"] for d in read_documents if d.get("uuid")]

    return (True, gold_answer, relevant_uuids)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate project-related cross-document questions."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Number of questions to generate (default: 50)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    print("Step 4: Generate Project-Related Questions")
    print("=" * 40)
    print("This script generates cross-document questions from project data.")
    print("Each question may require information from multiple project documents.")
    print()

    # Load projects
    projects = load_projects()
    if not projects:
        print("No project entries found in generation cache.")
        return
    print(f"Loaded {len(projects)} projects from generation cache.")

    # Load UUID index, rebuilding if needed UUIDs are missing
    needed_uuids: set[str] = set()
    for p in projects:
        needed_uuids.update(p.get("documents", []))

    uuid_index = ensure_uuids_resolved(needed_uuids)
    print(f"UUID index has {len(uuid_index)} entries.")

    # Load project usage cache
    project_usage = load_project_usage()

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

        # Select the least-used project
        project = select_next_project(projects, project_usage)
        project_file = project["project_outline_file"]
        print(f"Project: {project_file}")

        # Resolve document UUIDs to paths
        doc_uuids = project.get("documents", [])
        doc_paths: list[str] = []
        for uuid in doc_uuids:
            path = uuid_index.get(uuid)
            if path:
                doc_paths.append(path)

        if len(doc_paths) < 3:
            print(f"Skipping: only {len(doc_paths)} resolvable documents (need >= 3)")
            fail_count += 1
            errors.append(f"{project_file}: Too few resolvable documents")
            # Mark as used so we don't get stuck on the same project
            project_usage[project_file] = project_usage.get(project_file, 0) + 1
            continue

        print(f"  Documents: {len(doc_paths)} resolvable out of {len(doc_uuids)}")

        # Set up tools
        doc_read_tool = DocumentReadTool(
            base_dir=SOURCES_DIR,
            generated_doc_contents=True,
            display_name="project_documents",
        )
        tool_runner = ToolRunner()
        tool_runner.register(doc_read_tool)

        # Format prompt
        project_overview = project.get("description", "")
        project_document_paths = "\n".join(doc_paths)

        prompt = PROJECT_RELATED_QUERIES_PROMPT.format(
            project_overview=project_overview,
            project_document_paths=project_document_paths,
        )

        # Generate question via auto conversation
        print("\n--- Generating Question ---")
        llm = get_llm(tools=[doc_read_tool.schema], reasoning_level="high", quiet=args.quiet)
        messages: list[Message] = [Message(role="user", content=prompt)]

        try:
            question = run_auto_conversation(
                llm, tool_runner, messages, max_tool_cycles=20, quiet=args.quiet
            )
            question = question.strip()
        except RuntimeError as e:
            fail_count += 1
            errors.append(f"{project_file}: {e}")
            print(f"\nFailed: {e}")
            continue

        if not question:
            fail_count += 1
            errors.append(f"{project_file}: LLM returned empty response")
            print("\nFailed: LLM returned empty response")
            continue

        read_docs = doc_read_tool.read_documents
        if not read_docs:
            fail_count += 1
            errors.append(f"{project_file}: No documents were read by LLM")
            print("\nFailed: No documents were read by LLM")
            continue

        print(f"\nQuestion: {question}")
        print(f"Documents read: {len(read_docs)}")

        # Validate the question
        print("\n--- Validating Question ---")
        valid, gold_answer, relevant_uuids = validate_project_question(
            question, read_docs, quiet=args.quiet
        )

        if not valid or not gold_answer or not relevant_uuids:
            fail_count += 1
            errors.append(f"{project_file}: Question validation failed")
            print("\nFailed: Question validation failed")
            continue

        # Extract answer facts
        print("\n--- Extracting Answer Facts ---")
        answer_facts = extract_answer_facts(question, gold_answer, quiet=args.quiet)

        if not answer_facts:
            fail_count += 1
            errors.append(f"{project_file}: Answer fact extraction failed")
            print("\nFailed: Answer fact extraction failed")
            continue

        # Generate question ID
        question_id = f"qst_{next_question_id:04d}"

        # Derive source types from relevant UUIDs
        source_types = sorted(set(
            extract_source_type(uuid_index[uuid])
            for uuid in relevant_uuids
            if uuid in uuid_index
        ))

        # Append to questions file
        save_question(
            question_id=question_id,
            question=question,
            expected_doc_ids=relevant_uuids,
            source_types=source_types,
            gold_answer=gold_answer,
            answer_facts=answer_facts,
            question_type="project_related",
        )
        next_question_id += 1

        # Update project usage
        project_usage[project_file] = project_usage.get(project_file, 0) + 1
        save_project_usage(project_usage)

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
