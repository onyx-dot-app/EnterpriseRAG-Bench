"""Script for generating and enriching projects based on company context."""

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.llm.interface import LLMInterface, Message, ToolCall
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    DATA_CLEAN_DIR,
    INITIATIVES_PATH,
    PROJECT_LIST_PATH,
    PROJECTS_CACHE_DIR,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.projects import PROJECTS_ENRICHMENT_PROMPT, PROJECTS_SYSTEM_PROMPT
from src.schemas.project_enrichment import (
    EXPECTED_FORMAT_UNESCAPED,
    filter_invalid_paths,
    parse_project_enrichment,
    validate_project_enrichment,
)
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import (
    GlobTool,
    ReadEmployeeDirectoryTool,
    ReadTool,
    TreeTool,
    WriteTool,
)


def load_file(path: str) -> str:
    """Load a file and return its contents."""
    with open(path) as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"File at {path} is empty")
    return content


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


def run_auto_conversation(
    llm: LLMInterface,
    tool_runner: ToolRunner,
    messages: list[Message],
    max_tool_cycles: int = 20,
    max_iterations: int = 50,
) -> str:
    """
    Run a conversation automatically without user input until completion.

    Args:
        llm: The LLM instance with tools configured.
        tool_runner: The tool runner with registered tools.
        messages: The conversation messages (modified in place).
        max_tool_cycles: Maximum number of tool call cycles before forcing output.
        max_iterations: Maximum total LLM calls to prevent infinite loops.

    Returns:
        The final text response from the LLM.
    """
    tool_cycles = 0
    current_llm = llm

    for _ in range(max_iterations):
        full_response = ""
        tool_calls: list[ToolCall] = []

        for chunk in current_llm.generate(messages):
            if isinstance(chunk, str):
                full_response += chunk
            elif isinstance(chunk, ToolCall):
                tool_calls.append(chunk)

        # Handle tool calls
        if tool_calls:
            tool_cycles += 1

            # Check if we've hit the tool cycle limit
            if tool_cycles >= max_tool_cycles:
                # Add a message telling the LLM to output the JSON now
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "You have used the maximum number of tool calls. "
                            "Please output the final JSON now without any more tool calls."
                        ),
                    )
                )
                # Create a new LLM instance without tools to force text output
                current_llm = get_llm(tools=None)
                continue

            for tool_call in tool_calls:
                messages.append(
                    Message(role="tool_call", content="", tool_call=tool_call)
                )
                result = tool_runner.run(tool_call.name, **tool_call.args)
                messages.append(
                    Message(role="tool_result", content=result, call_id=tool_call.call_id)
                )
            continue

        # No tool calls = final response
        if full_response:
            messages.append(Message(role="assistant", content=full_response))
            return full_response

    raise RuntimeError(f"Max iterations ({max_iterations}) exceeded")


def extract_json_from_response(response: str) -> str:
    """
    Extract JSON string from LLM response.

    Args:
        response: The LLM response text.

    Returns:
        The extracted JSON string.

    Raises:
        ValueError: If no JSON found in response.
    """
    # Try to find JSON in a code block first
    json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
    if json_match:
        return json_match.group(1)

    # Try to find raw JSON object
    json_match = re.search(r"\{.*\}", response, re.DOTALL)
    if json_match:
        return json_match.group(0)

    raise ValueError(f"No JSON found in response: {response[:500]}...")


def enrich_single_project(
    project_name: str,
    project_description: str,
    company_overview: str,
    source_list: str,
) -> dict:
    """
    Enrich a single project using the LLM with validation and retry.

    Args:
        project_name: Name of the project.
        project_description: One-line description.
        company_overview: Company overview content.
        source_list: List of source directories.

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
    employee_llm = get_llm()
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
        ]
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
    response = run_auto_conversation(llm, tool_runner, messages)

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

    response = run_auto_conversation(llm, tool_runner, messages)

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
        )

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Write output
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        return (name, True, f"Created: {filename}")

    except Exception as e:
        return (name, False, f"Error: {e}")


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
        output_path = os.path.join(PROJECTS_CACHE_DIR, filename)
        if not os.path.exists(output_path):
            pending.append((name, desc))

    if not pending:
        print("All projects already enriched. Done.")
        return

    print(f"{len(projects) - len(pending)} already enriched, {len(pending)} remaining.")
    print(f"Starting enrichment with max_parallelization={max_parallelization}...")
    print()

    # Process projects in parallel with progress bar
    succeeded = 0
    failed_projects: list[tuple[str, str]] = []  # (name, error_message)

    with ThreadPoolExecutor(max_workers=max_parallelization) as executor:
        futures = {
            executor.submit(
                process_single_project,
                project,
                company_overview,
                source_list,
                PROJECTS_CACHE_DIR,
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


def run_interactive_generation() -> None:
    """Run the interactive project list generation phase."""
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

    # Interactive loop
    while True:
        # Check if project list was written
        if os.path.exists(PROJECT_LIST_PATH):
            print("\nProjects generation complete!")
            print(f"Project list saved to {PROJECT_LIST_PATH}")
            break

        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("Goodbye!")
                return  # Exit without enrichment

            conversation.run_turn(user_input)
            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            return  # Exit without enrichment


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
        line_count = len(content.strip().splitlines())
        print(f"Project list contains {line_count} projects.")
    else:
        print("Phase 1: Interactive Project List Generation")
        print("-" * 40)
        run_interactive_generation()

        # Check if generation was completed or user quit
        if not os.path.exists(PROJECT_LIST_PATH):
            print("Project list not generated. Exiting.")
            return

    # Phase 2: Enrich projects
    enrich_projects(max_parallelization=args.max_parallelization)


if __name__ == "__main__":
    main()
