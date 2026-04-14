"""Script for generating and enriching projects based on company context.

Runs a multi-phase pipeline: (1) interactive project list creation, (2) parallel
enrichment of each project with file paths and descriptions, (3) deduplication of
conflicting file paths across projects, and (4) people assignment from the employee
directory. Projects break high-level initiatives into smaller efforts of ~100 documents.

Usage:
    python -m src.scripts.data_gen_stage_1_generate_clean_data.step_6_generate_projects [OPTIONS]

Args:
    --max-parallelization  Number of projects to enrich in parallel (default: 5)
    --dedup-parallelism    Number of parallel deduplication operations (default: 20)
"""

import argparse
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.llm import Message, get_llm, run_auto_conversation
from src.llm.conversation import Conversation
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    EMPLOYEE_DIRECTORY_PATH,
    INITIATIVES_PATH,
    PROJECT_LIST_PATH,
    PROJECTS_DIR,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.projects import (
    PROJECT_DEDUP_PROMPT,
    PROJECT_PEOPLE_PROMPT,
    PROJECTS_ENRICHMENT_PROMPT,
    PROJECTS_SYSTEM_PROMPT,
)
from src.schemas.project_enrichment import (
    EXPECTED_FORMAT_UNESCAPED,
    filter_invalid_paths,
    filter_invalid_people,
    parse_project_enrichment,
    parse_project_people,
    validate_project_enrichment,
    validate_project_people,
)
from src.utils.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import (
    GlobTool,
    ReadEmployeeDirectoryTool,
    ReadTool,
    TreeTool,
    WriteTool,
)
from src.utils import (
    confirm_regenerate,
    default_resolver,
    extract_json_from_response,
    load_file,
    load_json_file,
    write_json_file,
)

STEP_OVERVIEW = """\
This script generates and enriches projects based on company context.
Projects are smaller in scope than initiatives - concrete work items for teams.
Each project produces a set of cross-referenced, logically coherent documents.
Enrichment outlines the files to create per project, \
their high-level contents, and the relevant people.

Phases:
  1. Interactive project list generation
  2. Enrich projects with file paths and descriptions
  3. Deduplicate conflicting file paths
  4. Populate people for each project
"""


def parse_project_list(content: str) -> list[tuple[str, str]]:
    """
    Parse project list file into list of (name, description) tuples.

    Format:
        # Section Header
        project_name: One line description.

    Lines are grouped under headers. Empty lines or new headers end a section.
    The description is formatted as:
        General area: {header without #}  (omitted if no header)
        Project name: {name}  (omitted if no colon separator)
        Project description: {one-liner or full line}
    """
    # First pass: build list of (header or None, line) tuples
    entries: list[tuple[str | None, str]] = []
    current_header: str | None = None

    for line in content.splitlines():
        stripped = line.strip()

        # Empty line ends current section
        if not stripped:
            current_header = None
            continue

        # New header
        if stripped.startswith("#"):
            current_header = stripped
            continue

        # Project line
        if stripped:
            entries.append((current_header, stripped))

    # Second pass: build project list
    projects = []
    for header, line in entries:
        parts = []

        # Add general area if header exists
        if header:
            area = header.lstrip("#").strip()
            parts.append(f"General area: {area}")

        # Check if line has name: description format
        if ":" in line:
            name, one_liner = line.split(":", 1)
            name = name.strip()
            one_liner = one_liner.strip()
            parts.append(f"Project name: {name}")
            parts.append(f"Project description: {one_liner}")
        else:
            # No colon, use whole line as description
            name = line
            parts.append(f"Project description: {line}")

        description = "\n".join(parts)
        projects.append((name, description))

    return projects


def project_name_to_filename(name: str) -> str:
    """
    Convert project name to a safe filename.

    Examples:
        "Mixed-workload scheduling policy" -> "mixed_workload_scheduling_policy.json"
        "RBAC v2 design + implementation" -> "rbac_v2_design_implementation.json"
    """
    # Lowercase
    filename = name.lower()
    # Replace special characters with underscores
    filename = re.sub(r"[^a-z0-9]+", "_", filename)
    # Remove leading/trailing underscores
    filename = filename.strip("_")
    # Add extension
    return f"{filename}.json"


def get_source_list(sources_dir: str) -> str:
    """Get top-level source directory names."""
    entries = sorted(os.listdir(sources_dir))
    dirs = [e for e in entries if os.path.isdir(os.path.join(sources_dir, e))]
    return "\n".join(dirs)


def enrich_single_project(
    project_name: str,
    project_description: str,
    company_overview: str,
    source_list: str,
    quiet: bool = False,
) -> dict:
    """
    Enrich a single project using the LLM with validation and retry.

    Args:
        project_name: Name of the project.
        project_description: One-line description.
        company_overview: Company overview content.
        source_list: List of source directories.
        quiet: If True, suppress LLM status output.

    Returns:
        Validated dict with description and files.

    Raises:
        ValueError: If validation fails after retry.
    """
    # Create tools
    tree_tool = TreeTool(base_dir=SOURCES_DIR)
    glob_tool = GlobTool(base_dir=SOURCES_DIR)
    read_tool = ReadTool(base_dir=SOURCES_DIR)

    # ReadEmployeeDirectoryTool needs its own LLM instance
    employee_llm = get_llm(quiet=quiet)
    employee_tool = ReadEmployeeDirectoryTool(llm=employee_llm)

    # Build the prompt (project_description already contains header + full line)
    prompt = PROJECTS_ENRICHMENT_PROMPT.format(
        project_description=project_description,
        company_overview_md_contents=company_overview,
        source_list=source_list,
    )

    # Initialize LLM with tool schemas
    llm = get_llm(
        tools=[
            tree_tool.schema,
            glob_tool.schema,
            read_tool.schema,
            employee_tool.schema,
        ],
        quiet=quiet,
    )

    # Create tool runner
    tool_runner = ToolRunner()
    tool_runner.register(tree_tool)
    tool_runner.register(glob_tool)
    tool_runner.register(read_tool)
    tool_runner.register(employee_tool)

    # Initialize messages
    messages: list[Message] = [Message(role="system", content=prompt)]

    # First attempt
    response = run_auto_conversation(llm, tool_runner, messages, quiet=quiet)

    try:
        json_str = extract_json_from_response(response)
        validation_error = validate_project_enrichment(json_str)

        if validation_error is None:
            # Valid - parse, filter invalid paths, and return
            result = parse_project_enrichment(json_str)
            result = filter_invalid_paths(result, default_resolver.base_dir)
            return result.model_dump()

    except ValueError as e:
        validation_error = str(e)

    # First attempt failed - retry once
    retry_prompt = (
        f"The JSON output was invalid. Error: {validation_error}\n\n"
        f"Please fix the JSON and output it again. Expected format:\n"
        f"```json\n{EXPECTED_FORMAT_UNESCAPED}\n```\n\n"
        "Make sure all paths start with 'sources/' and the files list is not empty."
    )
    messages.append(Message(role="user", content=retry_prompt))

    response = run_auto_conversation(llm, tool_runner, messages, quiet=quiet)

    try:
        json_str = extract_json_from_response(response)
        validation_error = validate_project_enrichment(json_str)

        if validation_error is None:
            # Valid on retry - parse, filter invalid paths, and return
            result = parse_project_enrichment(json_str)
            result = filter_invalid_paths(result, default_resolver.base_dir)
            return result.model_dump()

        # Still invalid after retry
        raise ValueError(f"Validation failed after retry: {validation_error}")

    except ValueError as e:
        raise ValueError(f"Failed after retry: {e}")


def process_single_project(
    project: tuple[str, str],
    company_overview: str,
    source_list: str,
    output_dir: str,
    quiet: bool = False,
) -> tuple[str, bool, str]:
    """
    Process a single project (for use with ThreadPoolExecutor).

    Returns:
        (project_name, success, message)
    """
    name, description = project
    filename = project_name_to_filename(name)
    output_path = os.path.join(output_dir, filename)

    # Skip if already exists
    if os.path.exists(output_path):
        return (name, True, f"Skipped (exists): {filename}")

    try:
        result = enrich_single_project(
            project_name=name,
            project_description=description,
            company_overview=company_overview,
            source_list=source_list,
            quiet=quiet,
        )

        # Write output (creates parent directories automatically)
        write_json_file(output_path, result)

        return (name, True, f"Created: {filename}")

    except Exception as e:
        return (name, False, f"Error: {e}")


def print_document_statistics(cache_dir: str) -> None:
    """
    Print statistics about generated documents per top-level source.

    Reads all JSON files in the cache directory and counts documents
    by top-level source directory (e.g., confluence, google_drive, slack).

    Args:
        cache_dir: Directory containing the enriched project JSON files.
    """
    from collections import Counter

    source_counts: Counter[str] = Counter()
    total_documents = 0
    total_projects = 0

    # Read all JSON files in the cache directory
    if not os.path.exists(cache_dir):
        return

    for filename in os.listdir(cache_dir):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(cache_dir, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)

            total_projects += 1
            files = data.get("files", [])

            for file_entry in files:
                path = file_entry.get("path", "")
                # Extract top-level source from path like "sources/confluence/..."
                parts = path.split("/")
                if len(parts) >= 2 and parts[0] == "sources":
                    top_level_source = parts[1]
                    source_counts[top_level_source] += 1
                    total_documents += 1

        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # Print statistics
    print()
    print("=" * 40)
    print("Document Statistics")
    print("=" * 40)
    print(f"Total projects: {total_projects}")
    print(f"Total documents: {total_documents}")
    print()
    print("Documents per source:")
    for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {source}: {count}")


def enrich_projects(max_parallelization: int = 5) -> None:
    """
    Enrich all projects with parallelization and progress bar.

    Args:
        max_parallelization: Maximum number of parallel enrichments.
    """
    print()
    print("=" * 40)
    print("Phase 2: Enrich Projects")
    print("=" * 40)

    # Load inputs
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    project_list_content = load_file(PROJECT_LIST_PATH)
    source_list = get_source_list(SOURCES_DIR)

    # Parse projects
    projects = parse_project_list(project_list_content)
    print(f"Found {len(projects)} projects in the list.")

    # Filter to projects not yet enriched
    pending: list[tuple[str, str]] = []
    for name, desc in projects:
        filename = project_name_to_filename(name)
        output_path = os.path.join(PROJECTS_DIR, filename)
        if not os.path.exists(output_path):
            pending.append((name, desc))

    if not pending:
        print("All projects already enriched.")
        print()
        print("To regenerate projects, remove everything under:")
        print(f"  {PROJECTS_DIR}")
        print_document_statistics(PROJECTS_DIR)
        return

    print(f"{len(projects) - len(pending)} already enriched, {len(pending)} remaining.")
    print(f"Starting enrichment with max_parallelization={max_parallelization}...")
    print()

    # Process projects in parallel with progress bar
    succeeded = 0
    failed_projects: list[tuple[str, str]] = []  # (name, error_message)

    # Use quiet mode when running in parallel to avoid garbled output
    use_quiet = max_parallelization > 1

    with ThreadPoolExecutor(max_workers=max_parallelization) as executor:
        futures = {
            executor.submit(
                process_single_project,
                project,
                company_overview,
                source_list,
                PROJECTS_DIR,
                use_quiet,
            ): project[0]
            for project in pending
        }

        with tqdm(total=len(pending), desc="Enriching projects") as pbar:
            for future in as_completed(futures):
                project_name = futures[future]
                try:
                    name, success, message = future.result()
                    if success:
                        succeeded += 1
                    else:
                        failed_projects.append((name, message))
                        tqdm.write(f"[FAIL] {name}: {message}")
                except Exception as e:
                    failed_projects.append((project_name, str(e)))
                    tqdm.write(f"[FAIL] {project_name}: {e}")
                pbar.update(1)

    # Summary
    print()
    print("=" * 40)
    print(f"Enrichment complete. {succeeded} succeeded, {len(failed_projects)} failed.")

    # Report failed projects
    if failed_projects:
        print()
        print("Failed projects:")
        for name, error in failed_projects:
            print(f"  - {name}: {error}")

    # Print document statistics
    print_document_statistics(PROJECTS_DIR)


def find_file_conflicts(projects_dir: str) -> dict[str, list[tuple[str, int]]]:
    """
    Find file path conflicts across all projects.

    Args:
        projects_dir: Directory containing project JSON files.

    Returns:
        Dict mapping conflicting file paths to list of (project_filename, file_index) tuples.
    """
    # Map file paths to list of (project_filename, file_index)
    path_to_projects: dict[str, list[tuple[str, int]]] = {}

    if not os.path.exists(projects_dir):
        return {}

    for filename in os.listdir(projects_dir):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(projects_dir, filename)
        try:
            data = load_json_file(filepath)
            files = data.get("files", [])
            for idx, file_entry in enumerate(files):
                path = file_entry.get("path", "")
                if path:
                    if path not in path_to_projects:
                        path_to_projects[path] = []
                    path_to_projects[path].append((filename, idx))
        except (json.JSONDecodeError, OSError):
            continue

    # Filter to only conflicts (paths used by more than one project/file)
    conflicts = {
        path: projects
        for path, projects in path_to_projects.items()
        if len(projects) > 1
    }
    return conflicts


def get_all_file_paths(projects_dir: str) -> set[str]:
    """Get all file paths across all projects."""
    all_paths: set[str] = set()

    if not os.path.exists(projects_dir):
        return all_paths

    for filename in os.listdir(projects_dir):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(projects_dir, filename)
        try:
            data = load_json_file(filepath)
            files = data.get("files", [])
            for file_entry in files:
                path = file_entry.get("path", "")
                if path:
                    all_paths.add(path)
        except (json.JSONDecodeError, OSError):
            continue

    return all_paths


def find_similar_files(file_path: str, all_paths: set[str]) -> list[str]:
    """
    Find files in the same directory that are similarly named (within 2 characters difference).

    Args:
        file_path: The file path to compare against.
        all_paths: Set of all existing file paths.

    Returns:
        List of similar file paths in the same directory.
    """
    directory = os.path.dirname(file_path)
    filename = os.path.basename(file_path)

    similar: list[str] = []
    for path in all_paths:
        if path == file_path:
            continue
        if os.path.dirname(path) != directory:
            continue

        other_filename = os.path.basename(path)

        # Check if filenames are within 2 characters difference (same length)
        if len(filename) == len(other_filename):
            diff_count = sum(1 for a, b in zip(filename, other_filename) if a != b)
            if diff_count <= 2:
                similar.append(path)

        # Also check if length difference is within 2 characters
        elif abs(len(filename) - len(other_filename)) <= 2:
            similar.append(path)

    return sorted(similar)


def _path_from_dedup_response(response: str) -> str | None:
    """Extract new_file_path from a dedup proposal response (for rejection user message)."""
    try:
        json_str = extract_json_from_response(response)
        data = json.loads(json_str)
        return data.get("new_file_path") or None
    except (json.JSONDecodeError, ValueError):
        return None


def propose_dedup(
    project_description: str,
    file_path: str,
    file_description: str,
    all_paths: set[str],
    previous_attempts: list[str] | None = None,
    quiet: bool = False,
) -> tuple[str, str, str] | None:
    """
    Use LLM to propose a deduplicated file path and description.

    Args:
        project_description: Description of the project.
        file_path: Current conflicting file path.
        file_description: Current file description.
        all_paths: Set of all existing file paths (to find similar files).
        previous_attempts: List of actual assistant outputs from previous attempts that failed.
        quiet: If True, suppress LLM status output.

    Returns:
        (new_file_path, new_file_description, raw_response) tuple, or None if failed.
    """
    # Find similarly-named files in the same directory
    similar_files = find_similar_files(file_path, all_paths)
    existing_files_str = "\n".join(similar_files) if similar_files else "(none)"

    prompt = PROJECT_DEDUP_PROMPT.format(
        existing_files=existing_files_str,
        project_description=project_description,
        file_path=file_path,
        file_description=file_description,
    )

    llm = get_llm(quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    # Add previous failed attempts (replay actual agent output)
    if previous_attempts:
        for prev_output in previous_attempts:
            messages.append(Message(role="assistant", content=prev_output))
            _path = _path_from_dedup_response(prev_output) or "that path"
            messages.append(
                Message(
                    role="user",
                    content=f"The proposed file '{_path}' already exists. Please try again with a different filename.",
                )
            )

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    try:
        json_str = extract_json_from_response(response)
        data = json.loads(json_str)
        new_path = data.get("new_file_path", "")
        new_desc = data.get("new_file_description", "")
        if new_path and new_desc:
            return (new_path, new_desc, response)
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def try_resolve_conflict(
    project_filename: str,
    file_index: int,
    conflicting_path: str,
    all_paths: set[str],
    paths_lock: threading.Lock,
    project_locks: dict[str, threading.Lock],
    projects_dir: str,
    max_attempts: int = 3,
) -> tuple[bool, str | None]:
    """
    Try to resolve a single file conflict automatically.

    Args:
        project_filename: Name of the project JSON file.
        file_index: Index of the file in the project's files list.
        conflicting_path: The conflicting file path.
        all_paths: Set of all existing file paths (to check for new collisions).
        paths_lock: Lock for thread-safe access to all_paths.
        project_locks: Dict of locks for thread-safe access to each project file.
        projects_dir: Directory containing project JSON files.
        max_attempts: Maximum number of LLM attempts.

    Returns:
        (success, new_path) tuple. If failed, new_path is None.
    """
    project_path = os.path.join(projects_dir, project_filename)

    # Load project data for the prompt (read-only, no lock needed)
    project_data = load_json_file(project_path)
    project_description = project_data.get("description", "")
    file_entry = project_data["files"][file_index]
    file_description = file_entry.get("description", "")

    previous_attempts: list[str] = []

    for _attempt in range(max_attempts):
        # Get a snapshot of all_paths for the LLM prompt (find_similar_files)
        with paths_lock:
            current_paths = set(all_paths)

        proposal = propose_dedup(
            project_description=project_description,
            file_path=conflicting_path,
            file_description=file_description,
            all_paths=current_paths,
            previous_attempts=previous_attempts if previous_attempts else None,
            quiet=True,
        )

        if proposal is None:
            continue

        new_path, new_desc, raw_response = proposal

        # Atomically check and add the new path
        with paths_lock:
            if new_path in all_paths and new_path != conflicting_path:
                previous_attempts.append(raw_response)
                continue

            # Reserve the new path immediately
            all_paths.add(new_path)

        # Success - update the project file with per-project lock
        # Re-load the file to get the latest version (another worker may have modified it)
        with project_locks[project_filename]:
            fresh_project_data = load_json_file(project_path)
            fresh_project_data["files"][file_index]["path"] = new_path
            fresh_project_data["files"][file_index]["description"] = new_desc
            write_json_file(project_path, fresh_project_data)

        return (True, new_path)

    # Failed after max_attempts
    return (False, None)


def apply_manual_dedup(
    project_filename: str,
    file_index: int,
    conflicting_path: str,
    new_filename: str,
    projects_dir: str,
) -> str:
    """
    Apply a manual dedup by updating the file path with a new filename.

    Args:
        project_filename: Name of the project JSON file.
        file_index: Index of the file in the project's files list.
        conflicting_path: The original conflicting file path.
        new_filename: The new filename (just the filename, not full path).
        projects_dir: Directory containing project JSON files.

    Returns:
        The new full path.
    """
    project_path = os.path.join(projects_dir, project_filename)
    project_data = load_json_file(project_path)

    # Build new path using the directory from the original path
    directory = os.path.dirname(conflicting_path)
    new_path = os.path.join(directory, new_filename)

    # Ensure it ends with .json
    if not new_path.endswith(".json"):
        new_path = f"{new_path}.json"

    # Update the project file
    project_data["files"][file_index]["path"] = new_path
    write_json_file(project_path, project_data)

    return new_path


def deduplicate_file_paths(max_parallelism: int = 10) -> None:
    """
    Phase 3: Check for and resolve file path conflicts across projects.

    Args:
        max_parallelism: Maximum number of parallel dedup operations.
    """
    print()
    print("=" * 40)
    print("Phase 3: Deduplicate File Paths")
    print("=" * 40)

    conflicts = find_file_conflicts(PROJECTS_DIR)

    if not conflicts:
        print("No file path conflicts found.")
        return

    # Build list of conflicts to resolve (skip first occurrence of each path)
    to_resolve: list[tuple[str, str, int]] = (
        []
    )  # (conflicting_path, project_filename, file_index)
    for conflicting_path, project_refs in conflicts.items():
        # Keep first occurrence, deduplicate the rest
        for i, (project_filename, file_index) in enumerate(project_refs):
            if i == 0:
                continue
            to_resolve.append((conflicting_path, project_filename, file_index))

    print(
        f"Found {len(conflicts)} conflicting paths, {len(to_resolve)} files need deduplication."
    )
    print(f"Running automatic deduplication with parallelism={max_parallelism}...")
    print()

    # Get all current paths for collision checking (thread-safe with lock)
    all_paths = get_all_file_paths(PROJECTS_DIR)
    paths_lock = threading.Lock()

    # Create per-project locks to prevent concurrent modifications to the same file
    unique_projects = {project_filename for _, project_filename, _ in to_resolve}
    project_locks: dict[str, threading.Lock] = {
        pf: threading.Lock() for pf in unique_projects
    }

    resolved = 0
    failed: list[tuple[str, str, int]] = (
        []
    )  # (conflicting_path, project_filename, file_index)

    with ThreadPoolExecutor(max_workers=max_parallelism) as executor:
        futures = {
            executor.submit(
                try_resolve_conflict,
                project_filename,
                file_index,
                conflicting_path,
                all_paths,
                paths_lock,
                project_locks,
                PROJECTS_DIR,
            ): (conflicting_path, project_filename, file_index)
            for conflicting_path, project_filename, file_index in to_resolve
        }

        with tqdm(total=len(to_resolve), desc="Deduplicating") as pbar:
            for future in as_completed(futures):
                conflicting_path, project_filename, file_index = futures[future]
                try:
                    success, _new_path = future.result()
                    if success:
                        resolved += 1
                    else:
                        failed.append((conflicting_path, project_filename, file_index))
                        tqdm.write(f"[FAIL] {project_filename}: {conflicting_path}")
                except Exception as e:
                    failed.append((conflicting_path, project_filename, file_index))
                    tqdm.write(f"[FAIL] {project_filename}: {conflicting_path} - {e}")
                pbar.update(1)

    print()
    print(f"Automatic deduplication: {resolved} resolved, {len(failed)} failed.")

    # Handle failed dedups - ask user for manual input
    if failed:
        print()
        print("=" * 40)
        print("Manual Resolution Required")
        print("=" * 40)
        print(f"{len(failed)} files need manual filename assignment.")
        print("For each, enter just the new filename (not the full path).")
        print("Type 'skip' to skip a file.")
        print()

        # Refresh all_paths after parallel updates
        all_paths = get_all_file_paths(PROJECTS_DIR)

        manual_resolved = 0
        manual_skipped = 0

        for conflicting_path, project_filename, file_index in failed:
            directory = os.path.dirname(conflicting_path)
            old_filename = os.path.basename(conflicting_path)

            print(f"\nProject: {project_filename}")
            print(f"Directory: {directory}/")
            print(f"Current filename: {old_filename}")

            while True:
                new_filename = input("New filename (or 'skip'): ").strip()

                if new_filename.lower() == "skip":
                    print("  Skipped.")
                    manual_skipped += 1
                    break

                if not new_filename:
                    print("  Filename cannot be empty.")
                    continue

                # Ensure it ends with .json
                if not new_filename.endswith(".json"):
                    new_filename = f"{new_filename}.json"

                # Build full path and check for collision
                new_full_path = os.path.join(directory, new_filename)
                if new_full_path in all_paths:
                    print(
                        f"  '{new_filename}' already exists in this directory. Try another."
                    )
                    continue

                # Apply the change
                actual_path = apply_manual_dedup(
                    project_filename=project_filename,
                    file_index=file_index,
                    conflicting_path=conflicting_path,
                    new_filename=new_filename,
                    projects_dir=PROJECTS_DIR,
                )
                all_paths.add(actual_path)
                print(f"  Updated to: {actual_path}")
                manual_resolved += 1
                break

        print()
        print(
            f"Manual resolution: {manual_resolved} resolved, {manual_skipped} skipped."
        )

    # Final summary
    print()
    print("=" * 40)
    print("Deduplication complete.")

    # Check for remaining conflicts
    remaining = find_file_conflicts(PROJECTS_DIR)
    if remaining:
        remaining_count = sum(len(refs) - 1 for refs in remaining.values())
        print()
        print("=" * 40)
        print(f"ERROR: {remaining_count} file path conflicts still remain.")
        print("=" * 40)
        print()
        print("Sometimes due to parallel handling of collisions or LLM failures,")
        print("there may be still remaining file collisions. Please run this step")
        print("again until there are no collisions or your final dataset may have")
        print("misleading documents.")
        print()
        print("IMPORTANT: You do not need to regenerate the projects.")
        print()
        raise RuntimeError(
            f"File path conflicts remain: {remaining_count} conflicts across {len(remaining)} paths"
        )
    else:
        print("All conflicts resolved.")


def run_interactive_generation() -> bool:
    """Run the interactive project list generation phase.

    Returns:
        True if project list was created, False if user quit early.
    """
    # Load context files
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    initiatives = load_file(INITIATIVES_PATH)
    source_tree = load_file(SOURCE_TREE_PATH)

    # Build the prompt
    prompt = PROJECTS_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        initiatives_md_contents=initiatives,
        source_tree_contents=source_tree,
    )

    # Create tools
    write_tool = WriteTool(file_path_override=PROJECT_LIST_PATH)

    # Initialize LLM with tool schemas
    llm = get_llm(tools=[write_tool.schema])

    # Create tool runner and register tools
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print("You will have a conversation with an LLM to guide you through the process.")
    input("Press Enter to begin...")
    print()
    print("Type 'quit' to exit.\n")

    # Add system prompt and get initial response
    conversation.add_system_message(prompt)
    conversation.generate_response()
    print()

    # Interactive loop - check for file creation after each turn
    while True:
        # Check if project list was written
        if os.path.exists(PROJECT_LIST_PATH):
            print(f"\nProject list saved to {PROJECT_LIST_PATH}")
            return True

        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("Goodbye!")
                return False

            conversation.run_turn(user_input)
            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            return False


def get_projects_without_people(projects_dir: str) -> list[str]:
    """
    Return list of project JSON filenames that don't have a 'people' field.

    Args:
        projects_dir: Directory containing project JSON files.

    Returns:
        List of filenames missing the 'people' field.
    """
    missing: list[str] = []
    if not os.path.exists(projects_dir):
        return missing

    for filename in os.listdir(projects_dir):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(projects_dir, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
            if "people" not in data or not data["people"]:
                missing.append(filename)
        except (json.JSONDecodeError, OSError):
            continue

    return missing


def add_people_to_project(
    project_path: str,
    company_overview: str,
    employee_directory: str,
    quiet: bool = False,
) -> tuple[bool, str]:
    """
    Add people to a single project file.

    Args:
        project_path: Path to the project JSON file.
        company_overview: Company overview content.
        employee_directory: Employee directory content.
        quiet: If True, suppress LLM status output.

    Returns:
        (success, message) tuple.
    """
    # Load existing project
    project_data = load_json_file(project_path)

    project_description = project_data.get("description", "")

    # Build prompt
    prompt = PROJECT_PEOPLE_PROMPT.format(
        project_description=project_description,
        company_overview=company_overview,
        employee_directory=employee_directory,
    )

    # Get LLM response (no tools needed)
    llm = get_llm(quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    # Extract and validate JSON
    try:
        json_str = extract_json_from_response(response)
        validation_error = validate_project_people(json_str)

        if validation_error:
            return (False, f"Validation error: {validation_error}")

        people_data = parse_project_people(json_str)

        # Filter invalid people (with recovery)
        valid_people = filter_invalid_people(
            people_data.people,
            project_description,
        )

        # Add people to project
        project_data["people"] = [p.model_dump() for p in valid_people]

        # Write back
        write_json_file(project_path, project_data)

        return (True, f"Added {len(valid_people)} people")

    except Exception as e:
        return (False, str(e))


def populate_project_people(max_parallelization: int = 5) -> None:
    """
    Phase 4: Add people to projects that are missing them.

    Args:
        max_parallelization: Maximum number of parallel operations.
    """
    print()
    print("=" * 40)
    print("Phase 4: Populate Project People")
    print("=" * 40)

    # Check which projects need people
    missing = get_projects_without_people(PROJECTS_DIR)

    if not missing:
        print("All projects already have people.")
        return

    print(f"Found {len(missing)} projects without people.")

    # Load context
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    employee_directory = load_file(EMPLOYEE_DIRECTORY_PATH)

    # Process in parallel
    succeeded = 0
    failed: list[tuple[str, str]] = []

    # Use quiet mode when running in parallel to avoid garbled output
    use_quiet = max_parallelization > 1

    with ThreadPoolExecutor(max_workers=max_parallelization) as executor:
        futures = {
            executor.submit(
                add_people_to_project,
                os.path.join(PROJECTS_DIR, filename),
                company_overview,
                employee_directory,
                use_quiet,
            ): filename
            for filename in missing
        }

        with tqdm(total=len(missing), desc="Adding people") as pbar:
            for future in as_completed(futures):
                filename = futures[future]
                try:
                    success, message = future.result()
                    if success:
                        succeeded += 1
                    else:
                        failed.append((filename, message))
                        tqdm.write(f"[FAIL] {filename}: {message}")
                except Exception as e:
                    failed.append((filename, str(e)))
                    tqdm.write(f"[FAIL] {filename}: {e}")
                pbar.update(1)

    print()
    print(f"Complete. {succeeded} succeeded, {len(failed)} failed.")

    if failed:
        print()
        print("Failed projects:")
        for filename, error in failed:
            print(f"  - {filename}: {error}")


def _has_project_files() -> bool:
    """Check if there are any project JSON files."""
    if not os.path.exists(PROJECTS_DIR):
        return False
    return any(f.endswith(".json") for f in os.listdir(PROJECTS_DIR))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and enrich projects based on company context."
    )
    parser.add_argument(
        "--max-parallelization",
        type=int,
        default=5,
        help="Maximum number of parallel enrichments (default: 5)",
    )
    parser.add_argument(
        "--dedup-parallelism",
        type=int,
        default=20,
        help="Maximum number of parallel deduplication operations (default: 20)",
    )
    args = parser.parse_args()

    print("Step 6: Generate Projects")
    print("=" * 40)
    print(STEP_OVERVIEW)

    # Check if projects already exist
    skip_generation = False
    if _has_project_files():
        if not confirm_regenerate("Projects"):
            skip_generation = True
            print(
                "Skipping generation phases, will run validation and completion phases..."
            )

    if not skip_generation:
        # Phase 1: Generate project list (interactive) or skip if exists
        if os.path.exists(PROJECT_LIST_PATH):
            print(f"Found cached project list at {PROJECT_LIST_PATH}")
            print("Skipping interactive generation...")
            with open(PROJECT_LIST_PATH) as f:
                content = f.read()
            projects = parse_project_list(content)
            print(f"Project list contains {len(projects)} projects.")
        else:
            print("Phase 1: Interactive Project List Generation")
            print("-" * 40)
            if not run_interactive_generation():
                print("Project list not generated. Exiting.")
                return

        # Phase 2: Enrich projects
        enrich_projects(max_parallelization=args.max_parallelization)

    # Phase 3: Deduplicate file paths (always run to catch conflicts)
    deduplicate_file_paths(max_parallelism=args.dedup_parallelism)

    # Phase 4: Populate people
    # NOTE: This is necessary as a separate step because the step above is already quite complex
    # and the miss rate when these were combined was too high.
    populate_project_people(max_parallelization=args.max_parallelization)

    # Update aggregate statistics
    project_count = len([f for f in os.listdir(PROJECTS_DIR) if f.endswith(".json")])
    update_statistics(
        "Stage 1: Generate Clean Data",
        "Step 6: Projects",
        {
            "total_projects": project_count,
        },
    )

    print("\nThis step is complete, go on to step 7 to generate project documents.")


if __name__ == "__main__":
    main()
