"""Script for generating constrained questions via corpus exploration.

Generates questions with qualifiers that narrow the correct answer to a small document
subset, even though many other documents are superficially relevant. An LLM agent uses
glob, grep, and read tools to explore the corpus, find topically related document
clusters, identify differentiating axes, and craft constrained queries with gold and
distractor documents.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_5_generate_constrained_questions [OPTIONS]

Args:
    --count        Number of questions to generate (default: 30)
    --parallelism  Number of parallel workers (default: 1)
    --quiet        Suppress LLM output streaming
"""

import argparse
import json
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from src.llm import Message, get_llm, run_auto_conversation
from src.paths import (
    GENERATED_DATA_DIR,
    GENERATION_CACHE_DIR,
    QUESTIONS_PATH,
    SOURCE_TREE_PATH,
)
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

STEP_OVERVIEW = """\
Generates questions with qualifiers that narrow the correct answer to a small
subset of documents, even though many others are superficially relevant. An LLM
agent explores the corpus to find document clusters, identify differentiating
axes, and craft constrained queries with gold and distractor documents.
"""

CACHE_PATH = os.path.join(GENERATION_CACHE_DIR, "constrained_questions.json")


# =============================================================================
# Used Documents Cache
# =============================================================================


def load_used_document_paths() -> list[str]:
    """Load list of document paths already used in constrained questions."""
    if os.path.exists(CACHE_PATH):
        try:
            data = load_json_file(CACHE_PATH)
            return list(data.get("used_document_paths", []))
        except Exception:
            pass
    return []


def save_used_document_paths(paths: list[str]) -> None:
    """Save list of used document paths to cache."""
    os.makedirs(GENERATION_CACHE_DIR, exist_ok=True)
    write_json_file(CACHE_PATH, {"used_document_paths": paths})


# =============================================================================
# Document Loading
# =============================================================================


def load_documents_by_paths(
    doc_paths: list[str],
    quiet: bool = False,
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
            documents.append(
                {
                    "path": rel_path,
                    "uuid": uuid,
                    "title": title,
                    "content": content,
                }
            )
        except (Exception, DocumentFieldError) as e:
            if not quiet:
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
        messages.append(
            Message(
                role="user",
                content="Approved. Please call the finish tool with the JSON output now.",
            )
        )
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
# Single Question Processing
# =============================================================================


def process_single_constrained_question(
    source_tree: str,
    used_document_paths: list[str],
    quiet: bool = False,
) -> tuple[bool, str, dict | None]:
    """
    Process a single constrained question end-to-end.

    Args:
        source_tree: Source directory tree string.
        used_document_paths: Snapshot of paths already used (passed to LLM).
        quiet: If True, suppress LLM output.

    Returns:
        (success, message, question_data) tuple.
        question_data includes gold_paths and distractor_paths for the caller
        to check overlap and update used_document_paths.
        On failure, question_data is None.
    """
    # Generate constrained question
    if not quiet:
        print("\n--- Exploring Corpus & Generating Question ---")

    query, gold_paths, distractor_paths = generate_constrained_question(
        source_tree, used_document_paths, quiet=quiet
    )

    if not query or not gold_paths:
        return (False, "Question generation failed", None)

    if not quiet:
        print(f"\nQuery: {query}")
        print(f"Gold documents: {gold_paths}")
        print(f"Distractor documents: {distractor_paths or []}")

    # Load all documents for validation
    if not quiet:
        print("\n--- Loading Documents ---")

    gold_docs = load_documents_by_paths(gold_paths, quiet=quiet)
    distractor_docs = load_documents_by_paths(distractor_paths or [], quiet=quiet)
    all_docs = gold_docs + distractor_docs

    if not gold_docs:
        return (False, "Failed to load any gold documents", None)

    # Validate the question
    if not quiet:
        print("\n--- Validating Question ---")

    valid, gold_answer, distractor_explanations, relevant_uuids = (
        validate_constrained_question(query, all_docs, quiet=quiet)
    )

    if not valid or not gold_answer or not relevant_uuids:
        return (False, "Question validation failed", None)

    if not quiet:
        print(f"\nGold answer: {gold_answer[:200]}...")

    # Extract answer facts
    if not quiet:
        print("\n--- Extracting Answer Facts ---")

    extracted_facts = extract_answer_facts(query, gold_answer, quiet=quiet)

    if not extracted_facts:
        return (False, "Answer fact extraction failed", None)

    if not quiet:
        print(f"\nExtracted {len(extracted_facts)} facts")

    # Combine extracted facts with distractor explanations
    answer_facts = extracted_facts + (distractor_explanations or [])

    # Derive source types from relevant UUIDs.
    # Paths are relative to GENERATED_DATA_DIR (e.g., "sources/confluence/..."),
    # so strip the "sources/" prefix before extracting the source type.
    source_types = sorted(
        set(
            extract_source_type(
                doc["path"].removeprefix("sources/").removeprefix("sources\\")
            )
            for doc in all_docs
            if doc.get("uuid") in relevant_uuids
        )
    )

    question_data = {
        "question": query,
        "expected_doc_ids": relevant_uuids,
        "source_types": source_types,
        "gold_answer": gold_answer,
        "answer_facts": answer_facts,
        "question_type": "constrained",
        "gold_paths": gold_paths,
        "distractor_paths": distractor_paths or [],
    }

    label = query[:60] if query else "unknown"
    return (True, f"{label}: Success", question_data)


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
        default=30,
        help="Number of questions to generate (default: 30)",
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

    print("Step 5: Generate Constrained Questions")
    print("=" * 40)
    print(STEP_OVERVIEW)

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
    print(
        f"Processing {args.count} constrained questions with parallelism={args.parallelism}."
    )
    print()

    success_count = 0
    fail_count = 0
    discard_count = 0
    errors: list[str] = []

    if args.parallelism <= 1:
        # Sequential mode — verbose output
        for i in range(args.count):
            print("\n" + "-" * 40)
            print(f"Question {i + 1} of {args.count}")
            print("-" * 40)

            success, message, question_data = process_single_constrained_question(
                source_tree, used_document_paths, quiet=args.quiet
            )

            if not success or not question_data:
                fail_count += 1
                errors.append(message)
                print(f"\nFailed: {message}")
                continue

            # Save
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

            # Update used document paths cache
            all_paths = question_data["gold_paths"] + question_data["distractor_paths"]
            for p in all_paths:
                if p not in used_document_paths:
                    used_document_paths.append(p)
            save_used_document_paths(used_document_paths)

            success_count += 1
            print(f"\nSaved question {question_id}")
    else:
        # Parallel mode — sliding window scheduler.
        # The main thread dispatches workers with the latest used_document_paths
        # snapshot, then processes results sequentially as they complete.
        # If a result's gold documents overlap with the (now-updated)
        # used_document_paths, the result is discarded.
        used_paths_set: set[str] = set(used_document_paths)
        completed = 0
        submitted = 0

        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures: dict = {}

            # Submit initial batch
            while submitted < args.count and len(futures) < args.parallelism:
                future = executor.submit(
                    process_single_constrained_question,
                    source_tree,
                    list(used_document_paths),  # snapshot
                    True,  # quiet=True for parallel workers
                )
                futures[future] = submitted
                submitted += 1

            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)

                for future in done:
                    futures.pop(future)
                    completed += 1

                    try:
                        success, message, question_data = future.result()
                    except Exception as e:
                        fail_count += 1
                        errors.append(str(e))
                        print(f"  [{completed}/{args.count}] ERROR: {e}")
                    else:
                        if not success or not question_data:
                            fail_count += 1
                            errors.append(message)
                            print(f"  [{completed}/{args.count}] FAIL: {message}")
                        else:
                            # Check for gold document overlap with current state
                            gold_paths = question_data["gold_paths"]
                            overlap = [p for p in gold_paths if p in used_paths_set]

                            if overlap:
                                discard_count += 1
                                msg = (
                                    f"Discarded: gold documents already used: {overlap}"
                                )
                                errors.append(msg)
                                print(f"  [{completed}/{args.count}] DISCARD: {msg}")
                            else:
                                # Save question
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

                                # Update used document paths
                                all_paths = (
                                    gold_paths + question_data["distractor_paths"]
                                )
                                for p in all_paths:
                                    if p not in used_paths_set:
                                        used_paths_set.add(p)
                                        used_document_paths.append(p)
                                save_used_document_paths(used_document_paths)

                                print(
                                    f"  [{completed}/{args.count}] OK: {message} -> {question_id}"
                                )

                    # Submit next work item with fresh used_document_paths
                    if submitted < args.count:
                        new_future = executor.submit(
                            process_single_constrained_question,
                            source_tree,
                            list(used_document_paths),  # fresh snapshot
                            True,
                        )
                        futures[new_future] = submitted
                        submitted += 1

    print("\n" + "=" * 40)
    print("Summary")
    print("=" * 40)
    print(f"Successfully generated: {success_count}")
    print(f"Failed: {fail_count}")
    if discard_count > 0:
        print(f"Discarded (gold doc overlap): {discard_count}")
    print(f"Total questions in file: {count_existing_questions()}")

    if errors:
        print()
        print("Errors:")
        for error in errors[:20]:
            print(f"  - {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    print("\nThis step is complete, go on to step 6 to generate conflicting questions.")


if __name__ == "__main__":
    main()
