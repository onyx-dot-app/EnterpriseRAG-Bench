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
    DEBUG_DIR,
    PROJECTS_DIR,
    SOURCES_DIR,
)
from src.prompts.document_generation import (
    AGENT_MD_FORMAT,
    DOCUMENT_GENERATION_SYSTEM_PROMPT,
    DOCUMENT_GENERATION_USER_PROMPT,
    FIELD_LABELER_PROMPT,
)
from src.schemas.field_labels import (
    parse_field_labels,
    validate_field_labels,
    validate_field_labels_against_document,
)
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import ReadTool


def load_file(path: str) -> str:
    """Load a file and return its contents."""
    with open(path) as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"File at {path} is empty")
    return content


def _is_simple_value(val: object) -> bool:
    """Check if a value is a simple string, primitive, or list of strings/primitives."""
    if isinstance(val, (str, int, float, bool, type(None))):
        return True
    if isinstance(val, list):
        return all(isinstance(item, (str, int, float, bool, type(None))) for item in val)
    return False


def validate_no_nested_dicts(data: dict) -> str | None:
    """
    Validate that a JSON dict has no nested dicts.

    All values must be strings, primitives, or lists of strings/primitives.

    Args:
        data: The parsed JSON dict.

    Returns:
        None if valid, error message if nested dicts found.
    """
    if not isinstance(data, dict):
        return "Top-level must be a dict"

    nested_keys = []
    for key, value in data.items():
        if not _is_simple_value(value):
            nested_keys.append(key)

    if nested_keys:
        return f"Nested dicts found in keys: {nested_keys}"

    return None


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
    quiet: bool = False,
) -> str:
    """
    Run a conversation automatically without user input until completion.

    Args:
        llm: The LLM instance with tools configured.
        tool_runner: The tool runner with registered tools.
        messages: The conversation messages (modified in place).
        max_tool_cycles: Maximum number of tool call cycles before forcing output.
        max_iterations: Maximum total LLM calls to prevent infinite loops.
        quiet: If True, suppress LLM status output for fallback LLM.

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
                current_llm = get_llm(tools=None, quiet=quiet)
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
    Extract JSON from LLM response by finding the outermost JSON structure.

    Tries multiple strategies:
    1. Find first '{' or '[' and match with last '}' or ']'
    2. Fallback: Look for JSON in markdown code blocks
    3. Fallback: Use regex to find JSON object/array

    Args:
        response: The LLM response text.

    Returns:
        The extracted JSON string.
    """
    import re

    response = response.strip()

    # Strategy 1: Find outermost JSON structure
    first_brace = response.find("{")
    first_bracket = response.find("[")

    if first_brace != -1 or first_bracket != -1:
        if first_brace == -1:
            start = first_bracket
            close_char = "]"
        elif first_bracket == -1:
            start = first_brace
            close_char = "}"
        elif first_brace < first_bracket:
            start = first_brace
            close_char = "}"
        else:
            start = first_bracket
            close_char = "]"

        last_close = response.rfind(close_char)
        if last_close != -1 and last_close >= start:
            candidate = response[start:last_close + 1]
            # Validate it's parseable JSON before returning
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass  # Fall through to backup strategies

    # Strategy 2 (fallback): Try to find JSON in a markdown code block
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
    if json_match:
        candidate = json_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Strategy 3 (fallback): Regex for JSON object or array
    json_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", response)
    if json_match:
        return json_match.group(1)

    return response


def label_document_fields(document: dict, quiet: bool = False) -> dict:
    """
    Run field labeling on a document to identify title and content fields.

    Args:
        document: The parsed document JSON.
        quiet: If True, suppress LLM status output.

    Returns:
        Updated document with title_field_name and content_field_names added.

    Raises:
        ValueError: If field labeling fails validation.
    """
    # Build the prompt
    prompt = FIELD_LABELER_PROMPT.format(
        json_document=json.dumps(document, indent=2),
    )

    # Get LLM response (no tools needed)
    llm = get_llm(quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    # Extract and validate JSON
    json_str = extract_json_from_response(response)

    validation_error = validate_field_labels(json_str)
    if validation_error:
        raise ValueError(f"Field labels validation failed: {validation_error}")

    field_labels = parse_field_labels(json_str)

    # Validate that the field names exist in the document
    doc_validation_error = validate_field_labels_against_document(field_labels, document)
    if doc_validation_error:
        raise ValueError(f"Field labels reference invalid keys: {doc_validation_error}")

    # Add the field labels to the document
    document["title_field_name"] = field_labels.title_field_name
    document["content_field_names"] = field_labels.content_field_names

    return document


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

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Write the file
        with open(full_path, "w") as f:
            json.dump(parsed, f, indent=2)

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
        project_json = load_project_json(project_file)
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
            project_json = load_project_json(project_file)
            files = project_json.get("files", [])
            total_files += len(files)
            for file_entry in files:
                file_path = file_entry.get("path", "")
                full_path = os.path.join(DATA_CLEAN_DIR, file_path)
                if os.path.exists(full_path):
                    existing_files.append(file_path)
                else:
                    pending_files += 1
        except Exception:
            pass

    print(f"Found {len(project_files)} projects with {total_files} total files.")
    print(f"Pending: {pending_files} files to generate, {len(existing_files)} already exist.")
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


def get_documents_without_labels(sources_dir: str) -> list[str]:
    """
    Return list of document JSON files that don't have field labels.

    Args:
        sources_dir: Directory containing source documents.

    Returns:
        List of file paths (relative to DATA_CLEAN_DIR) missing field labels.
    """
    missing: list[str] = []
    if not os.path.exists(sources_dir):
        return missing

    for root, _dirs, files in os.walk(sources_dir):
        for filename in files:
            if not filename.endswith(".json"):
                continue
            # Skip agents.md files
            if filename == "agents.md":
                continue

            filepath = os.path.join(root, filename)
            try:
                with open(filepath) as f:
                    data = json.load(f)
                # Check if field labels are missing
                if "title_field_name" not in data or "content_field_names" not in data:
                    # Get path relative to DATA_CLEAN_DIR
                    rel_path = os.path.relpath(filepath, DATA_CLEAN_DIR)
                    missing.append(rel_path)
            except (json.JSONDecodeError, OSError):
                continue

    return missing


def label_single_document(file_path: str, quiet: bool = False) -> tuple[bool, str]:
    """
    Add field labels to a single document file.

    Args:
        file_path: Path to the document file (relative to DATA_CLEAN_DIR).
        quiet: If True, suppress LLM status output.

    Returns:
        (success, message) tuple.
    """
    full_path = os.path.join(DATA_CLEAN_DIR, file_path)

    try:
        # Load existing document
        with open(full_path) as f:
            document = json.load(f)

        # Skip if already labeled
        if "title_field_name" in document and "content_field_names" in document:
            return (True, "Skipped (already labeled)")

        # Run field labeling
        labeled_doc = label_document_fields(document, quiet=quiet)

        # Write back
        with open(full_path, "w") as f:
            json.dump(labeled_doc, f, indent=2)

        return (True, "Labeled")

    except ValueError as e:
        return (False, str(e))
    except Exception as e:
        return (False, f"Error: {e}")


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

    sources_dir = os.path.join(DATA_CLEAN_DIR, "sources")

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
    parser.add_argument(
        "--labeling-parallelism",
        type=int,
        default=5,
        help="Number of documents to label in parallel (default: 5)",
    )
    args = parser.parse_args()

    print("Step 7: Generate Project Documents")
    print("=" * 40)
    print("This script generates individual document files for each project and adds field labels.")
    print("Phase 1: Generate documents based on project overviews")
    print("Phase 2: Add title/content field labels to documents")
    print()

    # Phase 1: Generate documents
    generate_documents(
        project_parallelism=args.project_parallelism,
        project_file_parallelism=args.project_file_parallelism,
    )

    # Phase 2: Label documents
    label_documents(max_parallelism=args.labeling_parallelism)


if __name__ == "__main__":
    main()
