"""Script for generating info_not_found questions via document cluster exploration.

Uses an LLM agent with corpus exploration tools to find clusters of topically related
documents and craft natural-sounding queries that are related to the cluster's topic
but not answerable from the corpus. Tests whether RAG systems can recognize when the
needed information is absent rather than hallucinating from superficially relevant docs.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_10_generate_info_not_found_questions [OPTIONS]

Args:
    --count  Number of questions to generate (default: 20)
    --quiet  Suppress LLM output streaming
"""

import argparse

from src.llm import Message, get_llm, run_auto_conversation
from src.paths import QUESTIONS_PATH, SOURCES_DIR
from src.prompts.info_not_found_question import (
    CONSTRAINED_QUERIES_SYSTEM_PROMPT,
    GOLD_ANSWER_AND_FACTS,
)
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import GlobTool, GrepTool, LsTool, ReadTool
from src.utils import (
    count_existing_questions,
    get_directory_tree,
    get_next_question_id,
    save_question,
    info_not_found_used_paths_cache,
)

STEP_OVERVIEW = """\
An LLM agent explores the corpus to find document clusters, then crafts queries
that are related to the cluster's topic but not answerable from the documents.
Tests whether RAG systems recognize when needed information is absent rather
than hallucinating.
"""


# =============================================================================
# Helpers
# =============================================================================


def _extract_read_paths(messages: list[Message]) -> list[str]:
    """Extract file paths from read tool calls in the conversation."""
    paths: list[str] = []
    for msg in messages:
        if msg.role == "tool_call" and msg.tool_call and msg.tool_call.name == "read":
            path = msg.tool_call.args.get("path", "")
            if path:
                paths.append(path)
    return paths


def _load_used_paths() -> list[str]:
    """Load previously used document paths from generation cache."""
    return info_not_found_used_paths_cache.load()


def _save_used_paths(new_paths: list[str]) -> None:
    """Append new paths to the used paths cache, deduplicating."""
    existing = set(info_not_found_used_paths_cache.load())
    to_add = [p for p in new_paths if p not in existing]
    for path in to_add:
        info_not_found_used_paths_cache.append(path)


def _format_used_paths(paths: list[str]) -> str:
    """Format used paths list for the prompt."""
    return "\n".join(paths) if paths else "(none)"


# =============================================================================
# Single Question Generation
# =============================================================================


def generate_info_not_found_question(
    source_tree: str,
    used_document_paths: str,
    quiet: bool = False,
) -> tuple[bool, str, list[str]]:
    """
    Generate a single info_not_found question by exploring documents.

    Returns:
        (success, query_or_error, read_paths) tuple.
    """
    prompt = CONSTRAINED_QUERIES_SYSTEM_PROMPT.format(
        source_tree_contents=source_tree,
        used_document_paths=used_document_paths,
    )

    # Set up tools
    glob_tool = GlobTool(base_dir=SOURCES_DIR)
    grep_tool = GrepTool(base_dir=SOURCES_DIR)
    ls_tool = LsTool(base_dir=SOURCES_DIR)
    read_tool = ReadTool(base_dir=SOURCES_DIR)

    tool_runner = ToolRunner()
    tool_runner.register(glob_tool)
    tool_runner.register(grep_tool)
    tool_runner.register(ls_tool)
    tool_runner.register(read_tool)

    tools = [glob_tool.schema, grep_tool.schema, ls_tool.schema, read_tool.schema]
    llm = get_llm(tools=tools, reasoning_level="high", quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    try:
        response = run_auto_conversation(
            llm, tool_runner, messages, max_tool_cycles=20, quiet=quiet
        )
    except RuntimeError as e:
        return (False, str(e), [])

    query = response.strip()
    if not query:
        return (False, "LLM returned empty response", [])

    read_paths = _extract_read_paths(messages)
    return (True, query, read_paths)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate info_not_found questions via document cluster exploration."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of questions to generate (default: 20)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    print("Step 10: Generate Info Not Found Questions")
    print("=" * 40)
    print(STEP_OVERVIEW)
    print()

    # Build source tree
    source_tree = get_directory_tree(SOURCES_DIR)

    # Load used paths from cache
    used_paths = _load_used_paths()
    print(f"Loaded {len(used_paths)} previously used document path(s) from cache.")

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
    print(f"Will generate {args.count} info_not_found question(s).")
    print()

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    for i in range(args.count):
        print("\n" + "-" * 40)
        print(f"Question {i + 1} of {args.count}")
        print("-" * 40)

        used_document_paths = _format_used_paths(used_paths)

        print("\n--- Exploring Documents & Generating Query ---")
        success, result, read_paths = generate_info_not_found_question(
            source_tree, used_document_paths, quiet=args.quiet
        )

        if not success:
            fail_count += 1
            errors.append(f"Question {i + 1}: {result}")
            print(f"\nFailed: {result}")
            continue

        query = result
        print(f"\nQuery: {query}")
        print(f"Documents explored: {len(read_paths)}")

        # Persist newly explored paths to cache and update local list
        _save_used_paths(read_paths)
        for p in read_paths:
            if p not in used_paths:
                used_paths.append(p)

        # Save question with predefined gold answer and facts
        question_id = f"qst_{next_question_id:04d}"
        save_question(
            question_id=question_id,
            question=query,
            expected_doc_ids=[],
            source_types=[],
            gold_answer=GOLD_ANSWER_AND_FACTS,
            answer_facts=[GOLD_ANSWER_AND_FACTS],
            question_type="info_not_found",
        )
        next_question_id += 1
        success_count += 1
        print(f"\nSaved question {question_id}")

    print("\n" + "=" * 40)
    print("Summary")
    print("=" * 40)
    print(f"Successfully generated: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Total questions in file: {count_existing_questions()}")
    print(f"Total used document paths in cache: {len(used_paths)}")

    if success_count < args.count:
        print(
            f"\nWarning: Only {success_count} questions created out of "
            f"{args.count} desired."
        )

    if errors:
        print()
        print("Errors:")
        for error in errors[:20]:
            print(f"  - {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    print("\nThis is the end of Stage 3 - Generating questions on the data.")


if __name__ == "__main__":
    main()
