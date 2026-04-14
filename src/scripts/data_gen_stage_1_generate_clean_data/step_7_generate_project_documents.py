"""Script for generating individual project document files.

Generates JSON documents for each project based on enriched project scaffolding. Each
document is aware of the company overview, project description, agents.md guidance, and
can read other project files for additional context. After generation, documents are
labeled with title/content field metadata and assigned UUIDs.

Usage:
    python -m src.scripts.data_gen_stage_1_generate_clean_data.step_7_generate_project_documents [OPTIONS]

Args:
    --project-parallelism       Number of projects to process in parallel (default: 5)
    --project-file-parallelism  Number of files to generate in parallel per project (default: 5)
    --labeling-parallelism      Number of documents to label in parallel (default: 20)
"""

import argparse
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.llm import Message, get_llm, run_auto_conversation
from src.paths import (
    AGENTS_MD_FILE,
    COMPANY_OVERVIEW_PATH,
    DEBUG_DIR,
    PROJECTS_DIR,
    SOURCES_DIR,
)
from src.prompts.document_generation import (
    AGENT_MD_FORMAT,
    DOCUMENT_GENERATION_SYSTEM_PROMPT,
    DOCUMENT_GENERATION_USER_PROMPT,
)
from src.utils.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import ReadTool
from src.utils import (
    add_dataset_doc_uuid,
    default_resolver,
    extract_json_from_response,
    get_documents_without_labels,
    label_single_document,
    load_file,
    load_json_file,
    projects_cache,
    validate_no_nested_dicts,
    write_json_file,
)

STEP_OVERVIEW = """\
Generates documents for each project based on the enriched project scaffolding.
Each document is aware of the company overview, project description, agents.md
guidance, and can read other project files for context. Documents are then
labeled with field metadata and assigned UUIDs.

Note: If any documents fail validation, you may need to rerun the script.

Phases:
  1. Generate documents based on project overviews
  2. Add title/content field labels to documents
  3. Add dataset_doc_uuid to all documents
  4. Write project cache to generation_cache
"""


def _save_debug_response(
    file_path: str,
    raw_response: str,
    extracted_json: str | None = None,
) -> None:
    """
    Save a failed response to the debug directory for inspection.

    Args:
        file_path: Original file path (e.g., "sources/slack/devex/thread.json")
        raw_response: The raw LLM response
        extracted_json: The extracted JSON string (if extraction succeeded)
    """
    # Ensure debug directory exists
    os.makedirs(DEBUG_DIR, exist_ok=True)

    # Use just the filename without the path
    filename = os.path.basename(file_path)
    # Change extension to .txt for the debug file
    debug_filename = os.path.splitext(filename)[0] + "_debug.txt"
    debug_path = os.path.join(DEBUG_DIR, debug_filename)

    with open(debug_path, "w") as f:
        f.write(f"=== Original file path ===\n{file_path}\n\n")
        f.write(f"=== Raw LLM response ===\n{raw_response}\n\n")
        if extracted_json is not None:
            f.write(f"=== Extracted JSON (before parsing) ===\n{extracted_json}\n")


def get_agents_md_along_path(file_path: str, base_dir: str) -> str:
    """
    Get all agents.md content along the path to the file.

    Args:
        file_path: Path like "sources/confluence/eng-runtime/doc.json"
        base_dir: Base directory (e.g., "generated_data")

    Returns:
        Formatted content of all agents.md files found along the path,
        using AGENT_MD_FORMAT with newline spaces between sections.
    """
    parts = file_path.split(os.sep)
    agents_sections = []

    # Walk from sources/ down to the parent directory of the file
    for i in range(1, len(parts)):
        partial_path = os.path.join(*parts[:i])
        agents_path = os.path.join(base_dir, partial_path, AGENTS_MD_FILE)

        if os.path.exists(agents_path):
            try:
                with open(agents_path) as f:
                    content = f.read().strip()
                if content:
                    formatted = AGENT_MD_FORMAT.format(
                        agents_md_path=f"{partial_path}/{AGENTS_MD_FILE}",
                        agents_md_contents=content,
                    )
                    agents_sections.append(formatted)
            except Exception:
                pass

    if not agents_sections:
        return "(No agents.md files found along the path)"

    return "\n\n".join(agents_sections)


def generate_single_file(
    file_path: str,
    file_description: str,
    project_json: dict,
    company_overview: str,
    quiet: bool = False,
) -> tuple[bool, str]:
    """
    Generate a single document file.

    Args:
        file_path: Path where the file should be created (e.g., "sources/confluence/...")
        file_description: Description of what the file should contain.
        project_json: The full project JSON for context.
        company_overview: Company overview content.
        quiet: If True, suppress LLM status output.

    Returns:
        (success, message) tuple.
    """
    # Check if file already exists
    full_path = default_resolver.to_absolute(file_path)
    if os.path.exists(full_path):
        return (True, "Skipped (exists)")

    # Get agents.md context along the path
    agents_context = get_agents_md_along_path(file_path, default_resolver.base_dir)

    # Build the system prompt
    system_prompt = DOCUMENT_GENERATION_SYSTEM_PROMPT.format(
        company_overview=company_overview,
        project_json=json.dumps(project_json, indent=2),
        agents_md_context=agents_context,
    )

    # Build the user prompt
    user_prompt = DOCUMENT_GENERATION_USER_PROMPT.format(
        file_path=file_path,
        file_description=file_description,
    )

    # Create tools
    read_tool = ReadTool(base_dir=SOURCES_DIR)

    # Initialize LLM with tool schemas
    llm = get_llm(tools=[read_tool.schema], quiet=quiet)

    # Create tool runner
    tool_runner = ToolRunner()
    tool_runner.register(read_tool)

    # Initialize messages with system and user prompts
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    response = ""
    json_content: str | None = None

    try:
        # Generate the document
        response = run_auto_conversation(llm, tool_runner, messages, quiet=quiet)

        # Extract JSON content
        json_content = extract_json_from_response(response)

        # Validate it's valid JSON
        parsed = json.loads(json_content)

        # Validate no nested dicts (values must be strings or list of strings)
        nested_error = validate_no_nested_dicts(parsed)
        if nested_error:
            _save_debug_response(file_path, response, json_content)
            return (False, f"Nested dicts: {nested_error}")

        # Write the file (creates parent directories automatically)
        write_json_file(full_path, parsed)

        return (True, "Created")

    except json.JSONDecodeError as e:
        # Save failed response to debug directory
        _save_debug_response(file_path, response, json_content)
        return (False, f"Invalid JSON: {e}")
    except Exception as e:
        # Save failed response for other errors too if we have a response
        if response:
            _save_debug_response(file_path, response, json_content)
        return (False, f"Error: {e}")


def process_project_files(
    project_name: str,
    project_json: dict,
    company_overview: str,
    file_parallelism: int,
    quiet: bool = False,
) -> tuple[int, int, int, list[tuple[str, str]]]:
    """
    Process all files for a single project.

    Args:
        project_name: Name of the project.
        project_json: The project JSON data.
        company_overview: Company overview content.
        file_parallelism: Number of files to process in parallel.
        quiet: If True, suppress LLM status output.

    Returns:
        (succeeded, skipped, failed, errors) tuple where errors is list of (path, error_msg).
    """
    files = project_json.get("files", [])
    if not files:
        return (0, 0, 0, [])

    # Filter out files that already exist
    pending_files = []
    skipped = 0
    for file_entry in files:
        file_path = file_entry.get("path", "")
        if default_resolver.exists(file_path):
            skipped += 1
        else:
            pending_files.append(file_entry)

    if not pending_files:
        return (0, skipped, 0, [])

    succeeded = 0
    failed = 0
    errors: list[tuple[str, str]] = []

    if file_parallelism <= 1:
        # Sequential processing
        for file_entry in pending_files:
            file_path = file_entry.get("path", "")
            file_desc = file_entry.get("description", "")

            success, message = generate_single_file(
                file_path=file_path,
                file_description=file_desc,
                project_json=project_json,
                company_overview=company_overview,
                quiet=quiet,
            )

            if success:
                succeeded += 1
            else:
                failed += 1
                errors.append((file_path, message))
    else:
        # Parallel processing within project - always use quiet mode
        with ThreadPoolExecutor(max_workers=file_parallelism) as executor:
            futures = {
                executor.submit(
                    generate_single_file,
                    file_entry.get("path", ""),
                    file_entry.get("description", ""),
                    project_json,
                    company_overview,
                    True,  # quiet=True for parallel
                ): file_entry.get("path", "")
                for file_entry in pending_files
            }

            for future in as_completed(futures):
                file_path = futures[future]
                try:
                    success, message = future.result()
                    if success:
                        succeeded += 1
                    else:
                        failed += 1
                        errors.append((file_path, message))
                except Exception as e:
                    failed += 1
                    errors.append((file_path, str(e)))

    return (succeeded, skipped, failed, errors)


def process_single_project(
    project_file: str,
    company_overview: str,
    file_parallelism: int,
    quiet: bool = False,
) -> tuple[str, int, int, int, list[tuple[str, str]]]:
    """
    Process a single project (wrapper for ThreadPoolExecutor).

    Returns:
        (project_name, succeeded, skipped, failed, errors)
    """
    project_name = os.path.splitext(os.path.basename(project_file))[0]

    try:
        project_json = load_json_file(project_file)
    except Exception as e:
        return (project_name, 0, 0, 1, [(project_file, f"Failed to load: {e}")])

    succeeded, skipped, failed, errors = process_project_files(
        project_name=project_name,
        project_json=project_json,
        company_overview=company_overview,
        file_parallelism=file_parallelism,
        quiet=quiet,
    )

    return (project_name, succeeded, skipped, failed, errors)


def print_document_statistics() -> None:
    """Print statistics about generated documents per top-level source."""
    source_counts: Counter[str] = Counter()
    total_documents = 0

    sources_dir = default_resolver.to_absolute("sources")
    if not os.path.exists(sources_dir):
        return

    # Walk through the sources directory and count JSON files
    for root, _dirs, files in os.walk(sources_dir):
        for filename in files:
            if filename.endswith(".json"):
                # Get relative path from sources/
                rel_path = os.path.relpath(root, sources_dir)
                top_level = rel_path.split(os.sep)[0]
                source_counts[top_level] += 1
                total_documents += 1

    print()
    print("=" * 40)
    print("Generated Document Statistics")
    print("=" * 40)
    print(f"Total documents: {total_documents}")
    print()
    print("Documents per source:")
    for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {source}: {count}")


def generate_documents(
    project_parallelism: int = 1,
    project_file_parallelism: int = 1,
) -> None:
    """
    Generate all project documents.

    Args:
        project_parallelism: Number of projects to process in parallel.
        project_file_parallelism: Number of files to process in parallel within each project.
    """
    print()
    print("=" * 40)
    print("Phase 1: Generate Documents")
    print("=" * 40)

    # Load company overview
    company_overview = load_file(COMPANY_OVERVIEW_PATH)

    # Get all project JSON files
    project_files = [
        os.path.join(PROJECTS_DIR, f)
        for f in os.listdir(PROJECTS_DIR)
        if f.endswith(".json")
    ]

    if not project_files:
        print("No project files found. Run step 6 first.")
        return

    # Count total and pending files across all projects
    total_files = 0
    pending_files = 0
    existing_files: list[str] = []
    for project_file in project_files:
        try:
            project_json = load_json_file(project_file)
            files = project_json.get("files", [])
            total_files += len(files)
            for file_entry in files:
                file_path = file_entry.get("path", "")
                if default_resolver.exists(file_path):
                    existing_files.append(file_path)
                else:
                    pending_files += 1
        except Exception:
            pass

    print(f"Found {len(project_files)} projects with {total_files} total files.")
    print(
        f"Pending: {pending_files} files to generate, {len(existing_files)} already exist."
    )
    print(f"Project parallelism: {project_parallelism}")
    print(f"File parallelism per project: {project_file_parallelism}")
    print()

    if pending_files == 0:
        print("All files already generated.")
        print_document_statistics()
        return

    total_succeeded = 0
    total_skipped = 0
    total_failed = 0
    all_errors: list[tuple[str, str, str]] = []  # (project, path, error)

    # Use quiet mode when running projects or files in parallel
    use_quiet = project_parallelism > 1 or project_file_parallelism > 1

    if project_parallelism <= 1:
        # Sequential project processing
        for project_file in tqdm(project_files, desc="Processing projects"):
            project_name, succeeded, skipped, failed, errors = process_single_project(
                project_file, company_overview, project_file_parallelism, use_quiet
            )
            total_succeeded += succeeded
            total_skipped += skipped
            total_failed += failed
            for path, error in errors:
                all_errors.append((project_name, path, error))
                tqdm.write(f"[FAIL] {project_name}: {path} - {error}")
    else:
        # Parallel project processing
        with ThreadPoolExecutor(max_workers=project_parallelism) as executor:
            futures = {
                executor.submit(
                    process_single_project,
                    project_file,
                    company_overview,
                    project_file_parallelism,
                    True,  # quiet=True for parallel
                ): project_file
                for project_file in project_files
            }

            with tqdm(total=len(project_files), desc="Processing projects") as pbar:
                for future in as_completed(futures):
                    try:
                        project_name, succeeded, skipped, failed, errors = (
                            future.result()
                        )
                        total_succeeded += succeeded
                        total_skipped += skipped
                        total_failed += failed
                        for path, error in errors:
                            all_errors.append((project_name, path, error))
                            tqdm.write(f"[FAIL] {project_name}: {path} - {error}")
                    except Exception as e:
                        project_file = futures[future]
                        project_name = os.path.splitext(os.path.basename(project_file))[
                            0
                        ]
                        all_errors.append((project_name, "", str(e)))
                        tqdm.write(f"[FAIL] {project_name}: {e}")
                    pbar.update(1)

    # Summary
    print()
    print("=" * 40)
    print(
        f"Generation complete. {total_succeeded} created, {total_skipped} skipped (already exist), {total_failed} failed."
    )

    if all_errors:
        print()
        print(f"Errors ({len(all_errors)}):")
        for project, path, error in all_errors[:20]:  # Show first 20 errors
            print(f"  - {project}: {path} - {error}")
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more errors")

    # Print statistics
    print_document_statistics()


def label_documents(max_parallelism: int = 5) -> None:
    """
    Phase 2: Add field labels to documents that are missing them.

    Args:
        max_parallelism: Maximum number of parallel operations.
    """
    print()
    print("=" * 40)
    print("Phase 2: Label Document Fields")
    print("=" * 40)

    sources_dir = default_resolver.to_absolute("sources")

    # Check which documents need labeling
    missing = get_documents_without_labels(sources_dir)

    if not missing:
        print("All documents already have field labels.")
        return

    print(f"Found {len(missing)} documents without field labels.")
    print()

    # Process in parallel
    succeeded = 0
    failed: list[tuple[str, str]] = []

    # Use quiet mode when running in parallel to avoid garbled output
    use_quiet = max_parallelism > 1

    with ThreadPoolExecutor(max_workers=max_parallelism) as executor:
        futures = {
            executor.submit(label_single_document, file_path, use_quiet): file_path
            for file_path in missing
        }

        with tqdm(total=len(missing), desc="Labeling documents") as pbar:
            for future in as_completed(futures):
                file_path = futures[future]
                try:
                    success, message = future.result()
                    if success:
                        succeeded += 1
                    else:
                        failed.append((file_path, message))
                        tqdm.write(f"[FAIL] {file_path}: {message}")
                except Exception as e:
                    failed.append((file_path, str(e)))
                    tqdm.write(f"[FAIL] {file_path}: {e}")
                pbar.update(1)

    print()
    print(f"Complete. {succeeded} labeled, {len(failed)} failed.")

    if failed:
        print()
        print(f"Failed documents ({len(failed)}):")
        for file_path, error in failed[:20]:
            print(f"  - {file_path}: {error}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more errors")


def add_dataset_uuids(max_parallelism: int = 20) -> None:
    """
    Phase 3: Add dataset_doc_uuid to all documents that don't have one.

    Args:
        max_parallelism: Maximum number of parallel operations.
    """
    print()
    print("=" * 40)
    print("Phase 3: Add Dataset Document UUIDs")
    print("=" * 40)

    sources_dir = default_resolver.to_absolute("sources")

    # Find all JSON files without dataset_doc_uuid
    files_to_process: list[str] = []
    for root, _dirs, files in os.walk(sources_dir):
        for filename in files:
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(root, filename)
            try:
                data = load_json_file(filepath)
                if "dataset_doc_uuid" not in data:
                    files_to_process.append(filepath)
            except (json.JSONDecodeError, OSError):
                continue

    if not files_to_process:
        print("All documents already have dataset_doc_uuid.")
        return

    print(f"Found {len(files_to_process)} documents without dataset_doc_uuid.")
    print()

    # Process in parallel
    added = 0
    failed: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=max_parallelism) as executor:
        futures = {
            executor.submit(add_dataset_doc_uuid, filepath): filepath
            for filepath in files_to_process
        }

        with tqdm(total=len(files_to_process), desc="Adding UUIDs") as pbar:
            for future in as_completed(futures):
                filepath = futures[future]
                try:
                    future.result()
                    added += 1
                except Exception as e:
                    rel_path = default_resolver.to_relative(filepath)
                    failed.append((rel_path, str(e)))
                    tqdm.write(f"[FAIL] {rel_path}: {e}")
                pbar.update(1)

    print()
    print(f"Complete. {added} UUIDs added, {len(failed)} failed.")

    if failed:
        print()
        print(f"Failed documents ({len(failed)}):")
        for filepath, error in failed[:20]:
            print(f"  - {filepath}: {error}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more errors")


def write_question_cache() -> None:
    """
    Phase 4: Write project entries to generation_cache/projects.json.

    Each entry contains:
    - project_outline_file: the project JSON filename
    - description: the project description
    - documents: list of dataset_doc_uuid values for project documents
    """
    print()
    print("=" * 40)
    print("Phase 4: Write to Generation Cache")
    print("=" * 40)

    # Get all project JSON files
    project_files = sorted([f for f in os.listdir(PROJECTS_DIR) if f.endswith(".json")])

    if not project_files:
        print("No project files found.")
        return

    print(f"Found {len(project_files)} projects to write.")
    print()

    entries: list[dict] = []
    failed: list[tuple[str, str]] = []

    for project_filename in project_files:
        project_path = os.path.join(PROJECTS_DIR, project_filename)

        try:
            project_json = load_json_file(project_path)
            description = project_json.get("description", "")
            files = project_json.get("files", [])

            # Collect dataset_doc_uuid from each document
            document_uuids: list[str] = []
            for file_entry in files:
                file_path = file_entry.get("path", "")
                full_path = default_resolver.to_absolute(file_path)

                if default_resolver.exists(file_path):
                    try:
                        doc_data = load_json_file(full_path)
                        uuid = doc_data.get("dataset_doc_uuid", "")
                        if uuid:
                            document_uuids.append(uuid)
                    except Exception:
                        pass

            entries.append(
                {
                    "project_outline_file": project_filename,
                    "description": description,
                    "documents": document_uuids,
                }
            )

        except Exception as e:
            failed.append((project_filename, str(e)))

    projects_cache.write_all(entries)
    print(
        f"Complete. {len(entries)} entries written to {projects_cache.path}, {len(failed)} failed."
    )

    if failed:
        print()
        print(f"Failed ({len(failed)}):")
        for project_file, error in failed:
            print(f"  - {project_file}: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate project document files based on enriched project data."
    )
    parser.add_argument(
        "--project-parallelism",
        type=int,
        default=5,
        help="Number of projects to process in parallel (default: 5)",
    )
    parser.add_argument(
        "--project-file-parallelism",
        type=int,
        default=5,
        help="Number of files to process in parallel within each project (default: 5)",
    )
    parser.add_argument(
        "--labeling-parallelism",
        type=int,
        default=20,
        help="Number of documents to label in parallel (default: 20)",
    )
    args = parser.parse_args()

    print("Step 7: Generate Project Documents")
    print("=" * 40)
    print(STEP_OVERVIEW)

    # Phase 1: Generate documents
    generate_documents(
        project_parallelism=args.project_parallelism,
        project_file_parallelism=args.project_file_parallelism,
    )

    # Phase 2: Label documents
    label_documents(max_parallelism=args.labeling_parallelism)

    # Phase 3: Add dataset UUIDs
    add_dataset_uuids(max_parallelism=args.labeling_parallelism)

    # Phase 4: Write to question cache
    write_question_cache()

    # Update aggregate statistics
    sources_dir = default_resolver.to_absolute("sources")
    source_counts: Counter[str] = Counter()
    total_docs = 0
    for root, _dirs, files in os.walk(sources_dir):
        for f in files:
            if f.endswith(".json"):
                rel_path = os.path.relpath(root, sources_dir)
                top_level = rel_path.split(os.sep)[0]
                source_counts[top_level] += 1
                total_docs += 1
    update_statistics(
        "Stage 1: Generate Clean Data",
        "Step 7: Documents",
        {
            "total_documents": total_docs,
            "documents_per_source": dict(source_counts),
        },
    )

    print(
        "\nThis step is complete, go on to step 8 to generate completeness documents."
    )


if __name__ == "__main__":
    main()
