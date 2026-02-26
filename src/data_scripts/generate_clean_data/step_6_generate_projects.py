"""Script for generating and enriching projects based on company context."""

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.llm import Message, get_llm, run_auto_conversation
from src.llm.conversation import Conversation
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    DATA_CLEAN_DIR,
    EMPLOYEE_DIRECTORY_PATH,
    INITIATIVES_PATH,
    PROJECT_LIST_PATH,
    PROJECTS_DIR,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.projects import (
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
from src.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import (
    GlobTool,
    ReadEmployeeDirectoryTool,
    ReadTool,
    TreeTool,
    WriteTool,
)
from src.utils import confirm_regenerate, extract_json_from_response, load_file, load_json_file, write_json_file


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
    messages: list[Message] = [
        Message(role="system", content=prompt)
    ]

    # First attempt
    response = run_auto_conversation(llm, tool_runner, messages, quiet=quiet)

    try:
        json_str = extract_json_from_response(response)
        validation_error = validate_project_enrichment(json_str)

        if validation_error is None:
            # Valid - parse, filter invalid paths, and return
            result = parse_project_enrichment(json_str)
            result = filter_invalid_paths(result, DATA_CLEAN_DIR)
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
            result = filter_invalid_paths(result, DATA_CLEAN_DIR)
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
            print("\nProjects generation complete!")
            print(f"Project list saved to {PROJECT_LIST_PATH}")
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
    Phase 3: Add people to projects that are missing them.

    Args:
        max_parallelization: Maximum number of parallel operations.
    """
    print()
    print("=" * 40)
    print("Phase 3: Populate Project People")
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
    args = parser.parse_args()

    # Check if projects already exist
    if _has_project_files():
        if not confirm_regenerate("Projects"):
            # Just update statistics and exit
            print("Updating statistics only...")
            project_count = len([f for f in os.listdir(PROJECTS_DIR) if f.endswith(".json")])
            update_statistics("Step 6: Projects", {
                "total_projects": project_count,
            })
            print("Statistics updated.")
            return

    print("Step 6: Generate Projects")
    print("=" * 40)
    print("This script generates and enriches projects based on company context.")
    print("Projects are smaller in scope than initiatives - concrete work items for teams.")
    print()

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

    # Phase 3: Populate people
    # NOTE: This is necessary as a separate step because the step above is already quite complex
    # and the miss rate when these were combined was too high.
    populate_project_people(max_parallelization=args.max_parallelization)

    # Update aggregate statistics
    project_count = len([f for f in os.listdir(PROJECTS_DIR) if f.endswith(".json")])
    update_statistics("Step 6: Projects", {
        "total_projects": project_count,
    })


if __name__ == "__main__":
    main()
