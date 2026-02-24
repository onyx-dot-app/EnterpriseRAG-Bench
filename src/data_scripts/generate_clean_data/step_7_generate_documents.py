"""Script for generating individual project document files."""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.llm import get_llm
from src.llm.interface import LLMInterface, Message, ToolCall
from src.paths import (
    AGENTS_MD_FILE,
    COMPANY_OVERVIEW_PATH,
    DATA_CLEAN_DIR,
    PROJECTS_DIR,
    SOURCES_DIR,
)
from src.prompts.document_generation import (
    AGENT_MD_FORMAT,
    DOCUMENT_GENERATION_SYSTEM_PROMPT,
    DOCUMENT_GENERATION_USER_PROMPT,
)
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import ReadEmployeeDirectoryTool, ReadTool


def load_file(path: str) -> str:
    """Load a file and return its contents."""
    with open(path) as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"File at {path} is empty")
    return content


def load_project_json(path: str) -> dict:
    """Load a project JSON file."""
    with open(path) as f:
        return json.load(f)


def get_agents_md_along_path(file_path: str, base_dir: str) -> str:
    """
    Get all agents.md content along the path to the file.

    Args:
        file_path: Path like "sources/confluence/eng-runtime/doc.json"
        base_dir: Base directory (e.g., "data_clean")

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


def run_auto_conversation(
    llm: LLMInterface,
    tool_runner: ToolRunner,
    messages: list[Message],
    max_tool_cycles: int = 10,
    max_iterations: int = 30,
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
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "You have used the maximum number of tool calls. "
                            "Please output the final document content now."
                        ),
                    )
                )
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
    Extract JSON from LLM response, handling markdown code blocks.

    Args:
        response: The LLM response text.

    Returns:
        The extracted JSON string.
    """
    import re

    response = response.strip()

    # Try to find JSON in a code block first
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
    if json_match:
        return json_match.group(1).strip()

    # If response starts with { or [, assume it's raw JSON
    if response.startswith("{") or response.startswith("["):
        return response

    # Try to find a JSON object or array in the response
    json_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", response)
    if json_match:
        return json_match.group(1)

    return response


def generate_single_file(
    file_path: str,
    file_description: str,
    project_json: dict,
    company_overview: str,
) -> tuple[bool, str]:
    """
    Generate a single document file.

    Args:
        file_path: Path where the file should be created (e.g., "sources/confluence/...")
        file_description: Description of what the file should contain.
        project_json: The full project JSON for context.
        company_overview: Company overview content.

    Returns:
        (success, message) tuple.
    """
    # Check if file already exists
    full_path = os.path.join(DATA_CLEAN_DIR, file_path)
    if os.path.exists(full_path):
        return (True, "Skipped (exists)")

    # Get agents.md context along the path
    agents_context = get_agents_md_along_path(file_path, DATA_CLEAN_DIR)

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

    # ReadEmployeeDirectoryTool needs its own LLM instance
    employee_llm = get_llm()
    employee_tool = ReadEmployeeDirectoryTool(llm=employee_llm)

    # Initialize LLM with tool schemas
    llm = get_llm(tools=[read_tool.schema, employee_tool.schema])

    # Create tool runner
    tool_runner = ToolRunner()
    tool_runner.register(read_tool)
    tool_runner.register(employee_tool)

    # Initialize messages with system and user prompts
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    try:
        # Generate the document
        response = run_auto_conversation(llm, tool_runner, messages)

        # Extract JSON content
        json_content = extract_json_from_response(response)

        # Validate it's valid JSON
        parsed = json.loads(json_content)

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Write the file
        with open(full_path, "w") as f:
            json.dump(parsed, f, indent=2)

        return (True, "Created")

    except json.JSONDecodeError as e:
        return (False, f"Invalid JSON: {e}")
    except Exception as e:
        return (False, f"Error: {e}")


def process_project_files(
    project_name: str,
    project_json: dict,
    company_overview: str,
    file_parallelism: int,
) -> tuple[int, int, int, list[tuple[str, str]]]:
    """
    Process all files for a single project.

    Args:
        project_name: Name of the project.
        project_json: The project JSON data.
        company_overview: Company overview content.
        file_parallelism: Number of files to process in parallel.

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
        full_path = os.path.join(DATA_CLEAN_DIR, file_path)
        if os.path.exists(full_path):
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
            )

            if success:
                succeeded += 1
            else:
                failed += 1
                errors.append((file_path, message))
    else:
        # Parallel processing within project
        with ThreadPoolExecutor(max_workers=file_parallelism) as executor:
            futures = {
                executor.submit(
                    generate_single_file,
                    file_entry.get("path", ""),
                    file_entry.get("description", ""),
                    project_json,
                    company_overview,
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
) -> tuple[str, int, int, int, list[tuple[str, str]]]:
    """
    Process a single project (wrapper for ThreadPoolExecutor).

    Returns:
        (project_name, succeeded, skipped, failed, errors)
    """
    project_name = os.path.splitext(os.path.basename(project_file))[0]

    try:
        project_json = load_project_json(project_file)
    except Exception as e:
        return (project_name, 0, 0, 1, [(project_file, f"Failed to load: {e}")])

    succeeded, skipped, failed, errors = process_project_files(
        project_name=project_name,
        project_json=project_json,
        company_overview=company_overview,
        file_parallelism=file_parallelism,
    )

    return (project_name, succeeded, skipped, failed, errors)


def print_document_statistics() -> None:
    """Print statistics about generated documents per top-level source."""
    from collections import Counter

    source_counts: Counter[str] = Counter()
    total_documents = 0

    sources_dir = os.path.join(DATA_CLEAN_DIR, "sources")
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
    print("Step 7: Generate Project Documents")
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
    for project_file in project_files:
        try:
            project_json = load_project_json(project_file)
            files = project_json.get("files", [])
            total_files += len(files)
            for file_entry in files:
                file_path = file_entry.get("path", "")
                full_path = os.path.join(DATA_CLEAN_DIR, file_path)
                if not os.path.exists(full_path):
                    pending_files += 1
        except Exception:
            pass

    print(f"Found {len(project_files)} projects with {total_files} total files.")
    print(f"Pending: {pending_files} files to generate, {total_files - pending_files} already exist.")
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

    if project_parallelism <= 1:
        # Sequential project processing
        for project_file in tqdm(project_files, desc="Processing projects"):
            project_name, succeeded, skipped, failed, errors = process_single_project(
                project_file, company_overview, project_file_parallelism
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
                ): project_file
                for project_file in project_files
            }

            with tqdm(total=len(project_files), desc="Processing projects") as pbar:
                for future in as_completed(futures):
                    try:
                        project_name, succeeded, skipped, failed, errors = future.result()
                        total_succeeded += succeeded
                        total_skipped += skipped
                        total_failed += failed
                        for path, error in errors:
                            all_errors.append((project_name, path, error))
                            tqdm.write(f"[FAIL] {project_name}: {path} - {error}")
                    except Exception as e:
                        project_file = futures[future]
                        project_name = os.path.splitext(os.path.basename(project_file))[0]
                        all_errors.append((project_name, "", str(e)))
                        tqdm.write(f"[FAIL] {project_name}: {e}")
                    pbar.update(1)

    # Summary
    print()
    print("=" * 40)
    print(f"Generation complete. {total_succeeded} created, {total_skipped} skipped (already exist), {total_failed} failed.")

    if all_errors:
        print()
        print(f"Errors ({len(all_errors)}):")
        for project, path, error in all_errors[:20]:  # Show first 20 errors
            print(f"  - {project}: {path} - {error}")
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more errors")

    # Print statistics
    print_document_statistics()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate project document files based on enriched project data."
    )
    parser.add_argument(
        "--project-parallelism",
        type=int,
        default=1,
        help="Number of projects to process in parallel (default: 1)",
    )
    parser.add_argument(
        "--project-file-parallelism",
        type=int,
        default=1,
        help="Number of files to process in parallel within each project (default: 1)",
    )
    args = parser.parse_args()

    print("Step 7: Generate Project Documents")
    print("=" * 40)
    print("This script generates individual document files for each project based on the project overviews created in the previous step.")
    print("This step is autonomous and will run without user input.")
    print()

    generate_documents(
        project_parallelism=args.project_parallelism,
        project_file_parallelism=args.project_file_parallelism,
    )


if __name__ == "__main__":
    main()
