"""Script for generating project-related cross-document questions.

Generates multi-document questions by giving the LLM a project overview and tools to
read project documents. The LLM explores documents to craft questions requiring
information from multiple sources (cross-cutting themes, contradictions, causal chains).
Projects are distributed evenly across questions to prevent over-sampling.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_4_generate_project_related_questions [OPTIONS]

Args:
    --count              Number of questions to generate (default: 40)
    --parallelism        Number of parallel workers (default: 1)
    --sweep-parallelism  Parallel workers for per-document sweep (default: 1)
    --quiet              Suppress LLM output streaming
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llm import Message, get_llm, run_auto_conversation
from src.paths import GENERATION_CACHE_DIR, QUESTIONS_PATH, SOURCES_DIR
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
from src.utils.eval_utils import evaluate_documents, update_gold_answer

STEP_OVERVIEW = """\
Gives the LLM a project overview and tools to read project documents. The LLM
explores documents to craft multi-document questions (cross-cutting themes,
contradictions, causal chains). The minimal set of documents needed is identified
as the gold set.
"""

PROJECT_USAGE_PATH = os.path.join(GENERATION_CACHE_DIR, "project_questions.json")


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
            return dict(data.get("project_usage", {}))
        except Exception:
            pass
    return {}


def save_project_usage(usage: dict[str, int]) -> None:
    """Save project usage counts to generation cache."""
    os.makedirs(GENERATION_CACHE_DIR, exist_ok=True)
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
# Post-Validation Document Sweep
# =============================================================================


def _evaluate_single_candidate(
    question: str,
    gold_doc_ids: list[str],
    candidate_dsid: str,
    uuid_index: dict[str, str],
) -> tuple[str, str | None, str]:
    """Evaluate a single candidate document against the gold set.

    Returns (dsid, classification_or_None, reason).
    """
    try:
        eval_result, eval_error = evaluate_documents(
            question=question,
            gold_doc_ids=gold_doc_ids,
            candidate_doc_ids=[candidate_dsid],
            document_path_map=uuid_index,
        )
    except Exception as e:
        return (candidate_dsid, None, str(e))

    if eval_result is None:
        return (candidate_dsid, None, eval_error or "no result")

    entry = eval_result.get(candidate_dsid, {})
    classification = entry.get("classification")
    reason = entry.get("reason", "")
    return (candidate_dsid, classification, reason)


def sweep_remaining_project_docs(
    question: str,
    relevant_uuids: list[str],
    all_project_uuids: list[str],
    uuid_index: dict[str, str],
    sweep_parallelism: int = 1,
    quiet: bool = False,
) -> list[str]:
    """Check remaining project docs for relevance to the generated question.

    Each candidate document is evaluated independently against the gold set.
    Use ``sweep_parallelism`` to run evaluations concurrently.

    Returns UUIDs of additional valid documents (may be empty).
    """
    relevant_set = set(relevant_uuids)
    remaining = [
        u for u in all_project_uuids if u not in relevant_set and u in uuid_index
    ]

    if not remaining:
        return []

    if not quiet:
        print(f"\n--- Sweeping {len(remaining)} remaining project documents ---")

    new_valid: list[str] = []
    completed = 0

    if sweep_parallelism <= 1:
        for dsid in remaining:
            completed += 1
            dsid, classification, reason = _evaluate_single_candidate(
                question, relevant_uuids, dsid, uuid_index
            )
            if classification == "valid":
                new_valid.append(dsid)
                if not quiet:
                    print(
                        f"  [{completed}/{len(remaining)}] " f"+ {dsid}: {reason[:80]}"
                    )
            elif classification is None and not quiet:
                print(
                    f"  [{completed}/{len(remaining)}] " f"[WARN] {dsid}: {reason[:80]}"
                )
    else:
        with ThreadPoolExecutor(max_workers=sweep_parallelism) as executor:
            futures = {
                executor.submit(
                    _evaluate_single_candidate,
                    question,
                    relevant_uuids,
                    dsid,
                    uuid_index,
                ): dsid
                for dsid in remaining
            }

            for future in as_completed(futures):
                completed += 1
                try:
                    dsid, classification, reason = future.result()
                except Exception as e:
                    dsid = futures[future]
                    if not quiet:
                        print(
                            f"  [{completed}/{len(remaining)}] " f"[WARN] {dsid}: {e}"
                        )
                    continue

                if classification == "valid":
                    new_valid.append(dsid)
                    if not quiet:
                        print(
                            f"  [{completed}/{len(remaining)}] "
                            f"+ {dsid}: {reason[:80]}"
                        )
                elif classification is None and not quiet:
                    print(
                        f"  [{completed}/{len(remaining)}] "
                        f"[WARN] {dsid}: {reason[:80]}"
                    )

    if not quiet:
        print(f"  Sweep found {len(new_valid)} additional valid documents")

    return new_valid


# =============================================================================
# Single Question Processing
# =============================================================================


def process_single_project_question(
    project: dict,
    doc_paths: list[str],
    uuid_index: dict[str, str],
    sweep_parallelism: int = 1,
    quiet: bool = False,
) -> tuple[bool, str, dict | None]:
    """
    Process a single project question end-to-end.

    Returns:
        (success, message, question_data) tuple.
        On failure, question_data is None.
    """
    project_file = project["project_outline_file"]

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
    if not quiet:
        print("\n--- Generating Question ---")

    llm = get_llm(tools=[doc_read_tool.schema], reasoning_level="high", quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    try:
        question = run_auto_conversation(
            llm, tool_runner, messages, max_tool_cycles=20, quiet=quiet
        )
        question = question.strip()
    except RuntimeError as e:
        return (False, f"{project_file}: {e}", None)

    if not question:
        return (False, f"{project_file}: LLM returned empty response", None)

    read_docs = doc_read_tool.read_documents
    if not read_docs:
        return (False, f"{project_file}: No documents were read by LLM", None)

    if not quiet:
        print(f"\nQuestion: {question}")
        print(f"Documents read: {len(read_docs)}")

    # Validate the question
    if not quiet:
        print("\n--- Validating Question ---")

    valid, gold_answer, relevant_uuids = validate_project_question(
        question, read_docs, quiet=quiet
    )

    if not valid or not gold_answer or not relevant_uuids:
        return (False, f"{project_file}: Question validation failed", None)

    if not quiet:
        print(f"\nDraft gold answer: {gold_answer[:200]}...")

    # Sweep remaining project docs for additional relevant documents
    all_project_uuids = project.get("documents", [])
    new_valid_uuids = sweep_remaining_project_docs(
        question=question,
        relevant_uuids=relevant_uuids,
        all_project_uuids=all_project_uuids,
        uuid_index=uuid_index,
        sweep_parallelism=sweep_parallelism,
        quiet=quiet,
    )

    if new_valid_uuids:
        relevant_uuids = relevant_uuids + new_valid_uuids

        if not quiet:
            print(
                f"\n--- Regenerating gold answer with "
                f"{len(relevant_uuids)} documents ---"
            )

        updated_answer = update_gold_answer(
            question=question,
            previous_gold_answer=gold_answer,
            valid_doc_ids=relevant_uuids,
            document_path_map=uuid_index,
        )

        if updated_answer:
            gold_answer = updated_answer

    # Extract answer facts (once, on the final gold answer)
    if not quiet:
        print("\n--- Extracting Answer Facts ---")

    answer_facts = extract_answer_facts(question, gold_answer, quiet=quiet)

    if not answer_facts:
        return (False, f"{project_file}: Answer fact extraction failed", None)

    if not quiet:
        print(f"\nExtracted {len(answer_facts)} facts")

    # Derive source types from relevant UUIDs
    source_types = sorted(
        set(
            extract_source_type(uuid_index[uuid])
            for uuid in relevant_uuids
            if uuid in uuid_index
        )
    )

    question_data = {
        "question": question,
        "expected_doc_ids": relevant_uuids,
        "source_types": source_types,
        "gold_answer": gold_answer,
        "answer_facts": answer_facts,
        "question_type": "project_related",
    }

    return (True, f"{project_file}: Success", question_data)


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
        default=40,
        help="Number of questions to generate (default: 40)",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1, verbose output)",
    )
    parser.add_argument(
        "--sweep-parallelism",
        type=int,
        default=1,
        help="Parallel workers for the per-document sweep (default: 1)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    print("Step 4: Generate Project-Related Questions")
    print("=" * 40)
    print(STEP_OVERVIEW)

    # Load projects
    projects = load_projects()
    if not projects:
        print("No project entries found in generation cache.")
        print(
            "Run Stage 1 Steps 6-7 first "
            "(step_6_generate_projects + step_7_generate_project_documents)."
        )
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

    # Pre-select all projects and resolve their doc paths.
    # Incrementing in-memory usage each time ensures even distribution.
    work_items: list[tuple[dict, list[str]]] = []
    pre_fail_count = 0
    pre_errors: list[str] = []

    for _ in range(args.count):
        project = select_next_project(projects, project_usage)
        project_file = project["project_outline_file"]

        # Always increment usage so we don't get stuck on the same project
        project_usage[project_file] = project_usage.get(project_file, 0) + 1

        # Resolve document UUIDs to paths
        doc_uuids = project.get("documents", [])
        doc_paths: list[str] = []
        for uuid in doc_uuids:
            path = uuid_index.get(uuid)
            if path:
                doc_paths.append(path)

        if len(doc_paths) < 3:
            pre_fail_count += 1
            pre_errors.append(f"{project_file}: Too few resolvable documents")
            continue

        work_items.append((project, doc_paths))

    if pre_fail_count > 0:
        print(f"Skipped {pre_fail_count} project selections (too few documents).")

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
        f"Processing {len(work_items)} project questions with parallelism={args.parallelism}."
    )
    print()

    success_count = 0
    fail_count = pre_fail_count
    errors: list[str] = list(pre_errors)

    if args.parallelism <= 1:
        # Sequential mode — verbose output
        for i, (project, doc_paths) in enumerate(work_items):
            project_file = project["project_outline_file"]
            print("\n" + "-" * 40)
            print(f"Question {i + 1} of {len(work_items)}")
            print(f"Project: {project_file}")
            print(f"  Documents: {len(doc_paths)} resolvable")
            print("-" * 40)

            success, message, question_data = process_single_project_question(
                project,
                doc_paths,
                uuid_index,
                sweep_parallelism=args.sweep_parallelism,
                quiet=args.quiet,
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

            # Save project usage after each success
            save_project_usage(project_usage)

            print(f"\nSaved question {question_id}")
    else:
        # Parallel mode — quiet workers, save incrementally as they complete
        completed = 0

        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures = {
                executor.submit(
                    process_single_project_question,
                    project,
                    doc_paths,
                    uuid_index,
                    args.sweep_parallelism,
                    True,  # quiet=True for parallel workers
                ): idx
                for idx, (project, doc_paths) in enumerate(work_items)
            }

            for future in as_completed(futures):
                completed += 1
                try:
                    success, message, question_data = future.result()
                except Exception as e:
                    fail_count += 1
                    errors.append(str(e))
                    print(f"  [{completed}/{len(work_items)}] ERROR: {e}")
                    continue

                if not success or not question_data:
                    fail_count += 1
                    errors.append(message)
                    print(f"  [{completed}/{len(work_items)}] FAIL: {message}")
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
                print(
                    f"  [{completed}/{len(work_items)}] OK: {message} -> {question_id}"
                )

        # Save project usage once after all parallel work completes
        save_project_usage(project_usage)

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

    print("\nThis step is complete, go on to step 5 to generate constrained questions.")


if __name__ == "__main__":
    main()
