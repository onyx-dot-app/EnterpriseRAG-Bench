"""Script for generating volume task documents per source type."""

import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.llm import Message, get_llm
from src.paths import (
    AGENTS_MD_FILE,
    COMPANY_OVERVIEW_PATH,
    INITIATIVES_PATH,
    SOURCES_DIR,
    VOLUME_DIR,
)
from src.prompts.volume_generation import ESTIMATION_OFF_PROMPT, TASKS_PROMPT, TOTAL_DOCS_PROMPT
from src.utils import extract_json_from_response, load_file
from src.utils.file_io import write_json_file
from src.utils.statistics import update_statistics
import re


def get_source_types() -> list[str]:
    """
    Get all top-level source type directories.

    Returns:
        Sorted list of source type names (e.g., ["confluence", "github", "slack"]).
    """
    if not os.path.exists(SOURCES_DIR):
        return []
    return sorted([
        d for d in os.listdir(SOURCES_DIR)
        if os.path.isdir(os.path.join(SOURCES_DIR, d)) and not d.startswith(".")
    ])


def count_existing_docs(source_type: str) -> int:
    """
    Count existing JSON documents in a source directory.

    Args:
        source_type: Name of the source type (e.g., "confluence").

    Returns:
        Number of .json files in the source directory (excluding agents.md).
    """
    source_path = os.path.join(SOURCES_DIR, source_type)
    if not os.path.exists(source_path):
        return 0

    count = 0
    for root, _dirs, files in os.walk(source_path):
        for filename in files:
            if filename.endswith(".json"):
                count += 1
    return count


def extract_total_docs_rule_based(agents_md_content: str) -> int | None:
    """
    Try to extract target document count from agents.md using rule-based parsing.

    Looks for patterns like:
        Target number of files:
        200000

    Args:
        agents_md_content: Content of the agents.md file.

    Returns:
        Extracted count or None if not found.
    """
    lines = agents_md_content.split("\n")
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if "target number of files" in line_lower or "target number of documents" in line_lower:
            # Look at the next line for the number
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # Try to extract a number
                match = re.match(r"^(\d+)", next_line)
                if match:
                    return int(match.group(1))
    return None


def extract_total_docs_llm(agents_md_content: str, quiet: bool = False) -> int | None:
    """
    Extract target document count from agents.md using LLM.

    Args:
        agents_md_content: Content of the agents.md file.
        quiet: If True, suppress LLM status output.

    Returns:
        Extracted count or None if not found/invalid.
    """
    prompt = TOTAL_DOCS_PROMPT.format(agents_md_contents=agents_md_content)

    llm = get_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    response = response.strip()

    # Check for N/A response
    if response.upper() == "N/A":
        return None

    # Try to extract integer
    try:
        return int(response)
    except ValueError:
        # Try to find a number in the response
        match = re.search(r"(\d+)", response)
        if match:
            return int(match.group(1))
        return None


def get_total_docs_for_source(source_type: str, quiet: bool = False) -> int:
    """
    Get the target total documents for a source type.

    First tries rule-based extraction from the top-level agents.md,
    then falls back to LLM extraction.

    Args:
        source_type: Name of the source type.
        quiet: If True, suppress LLM status output.

    Returns:
        Target document count, or 0 if not found.
    """
    # Read the top-level agents.md for this source
    agents_path = os.path.join(SOURCES_DIR, source_type, AGENTS_MD_FILE)
    if not os.path.exists(agents_path):
        return 0

    try:
        with open(agents_path) as f:
            content = f.read()
    except Exception:
        return 0

    # Try rule-based extraction first
    result = extract_total_docs_rule_based(content)
    if result is not None:
        return result

    # Fall back to LLM
    result = extract_total_docs_llm(content, quiet=quiet)
    return result if result is not None else 0


def get_source_tree(source_type: str) -> str:
    """
    Get the directory tree for a specific source type.

    Args:
        source_type: Name of the source type (e.g., "confluence").

    Returns:
        Tree output string for just that source directory.
    """
    source_path = os.path.join(SOURCES_DIR, source_type)
    if not os.path.exists(source_path):
        return f"(Source directory not found: {source_type})"

    result = subprocess.run(
        ["tree", "-d", source_type],
        cwd=SOURCES_DIR,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return f"(Error running tree: {result.stderr})"

    return result.stdout


def get_agents_md_for_source(source_type: str) -> str:
    """
    Get all agents.md files and their contents for a specific source type.

    Args:
        source_type: Name of the source type (e.g., "confluence").

    Returns:
        Formatted string containing all agents.md paths and contents.
    """
    source_path = os.path.join(SOURCES_DIR, source_type)
    if not os.path.exists(source_path):
        return f"(No agents.md files found for {source_type})"

    agents_sections = []

    for root, _dirs, files in os.walk(source_path):
        if AGENTS_MD_FILE in files:
            agents_path = os.path.join(root, AGENTS_MD_FILE)
            rel_path = os.path.relpath(agents_path, SOURCES_DIR)

            try:
                with open(agents_path) as f:
                    content = f.read().strip()
                if content:
                    formatted = f"""agents.md file path: {rel_path}
agents.md file contents:
```
{content}
```"""
                    agents_sections.append(formatted)
            except Exception:
                pass

    if not agents_sections:
        return f"(No agents.md files found for {source_type})"

    return "\n\n".join(agents_sections)


def validate_volume_json(json_str: str) -> str | None:
    """
    Validate that the JSON has string keys and integer values.

    Args:
        json_str: JSON string to validate.

    Returns:
        Error message if invalid, None if valid.
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    if not isinstance(data, dict):
        return "JSON must be an object/dict"

    for key, value in data.items():
        if not isinstance(key, str):
            return f"Key must be a string: {key}"

        # Value can be a string representation of an integer or an integer
        if isinstance(value, int):
            continue
        elif isinstance(value, str):
            try:
                int(value)
            except ValueError:
                return f"Value must be an integer (or string representation of integer): {key}={value}"
        else:
            return f"Value must be an integer or string: {key}={value}"

    return None


def get_total_from_json(json_str: str) -> int:
    """Get the total document count from a volume JSON string."""
    data = json.loads(json_str)
    return sum(int(count) for count in data.values())


def check_estimation_accuracy(
    estimated_total: int,
    target_total: int,
    tolerance: float = 0.1,
) -> tuple[bool, float]:
    """
    Check if the estimated total is within tolerance of the target.

    Args:
        estimated_total: Sum of documents from LLM topics.
        target_total: Expected document count.
        tolerance: Allowed percentage difference (default 10%).

    Returns:
        (is_accurate, off_percentage) tuple.
    """
    if target_total == 0:
        return (True, 0.0)

    off_percentage = abs(estimated_total - target_total) / target_total * 100
    is_accurate = off_percentage <= (tolerance * 100)
    return (is_accurate, off_percentage)


def normalize_volume_json(
    json_str: str,
    pre_existing_doc_count: int,
) -> dict:
    """
    Normalize the volume JSON to the structured format with topics and metadata.

    Args:
        json_str: Validated JSON string from LLM (topic -> count).
        pre_existing_doc_count: Number of existing documents in the source.

    Returns:
        Dict with structure:
        {
            "pre_existing_doc_count": int,
            "total_docs_in_topics": int,
            "remaining_doc_count": int,
            "topics": {topic: {"desired": count, "completed": 0}}
        }
    """
    data = json.loads(json_str)
    topics = {
        topic: {"desired": int(count), "completed": 0}
        for topic, count in data.items()
    }

    total_docs_in_topics = sum(int(count) for count in data.values())
    remaining_doc_count = max(0, total_docs_in_topics - pre_existing_doc_count)

    return {
        "pre_existing_doc_count": pre_existing_doc_count,
        "total_docs_in_topics": total_docs_in_topics,
        "remaining_doc_count": remaining_doc_count,
        "topics": topics,
    }


def generate_volume_for_source(
    source_type: str,
    company_overview: str,
    initiatives: str,
    source_list: str,
    quiet: bool = False,
    max_attempts: int = 5,
) -> tuple[bool, str, dict | None, bool]:
    """
    Generate volume tasks for a single source type.

    Args:
        source_type: Name of the source type.
        company_overview: Company overview content.
        initiatives: Initiatives content.
        source_list: List of all source types.
        quiet: If True, suppress LLM status output.
        max_attempts: Maximum number of attempts to get accurate estimation.

    Returns:
        (success, message, data, estimation_failed) tuple where:
        - success: Whether the file was created
        - message: Status message
        - data: The volume dict if successful
        - estimation_failed: Whether estimation accuracy check failed after all attempts
    """
    # Check if already generated
    output_path = os.path.join(VOLUME_DIR, f"{source_type}.json")
    if os.path.exists(output_path):
        return (True, "Skipped (exists)", None, False)

    # Count existing documents
    pre_existing_doc_count = count_existing_docs(source_type)

    # Get target volume from agents.md (total expected)
    total_target_volume = get_total_docs_for_source(source_type, quiet=quiet)
    if total_target_volume == 0:
        return (False, "Could not extract target volume from agents.md", None, False)

    # Effective target is total minus pre-existing
    effective_target = max(0, total_target_volume - pre_existing_doc_count)

    # If no docs needed, skip LLM and write empty topics
    if effective_target == 0:
        volume_data = {
            "pre_existing_doc_count": pre_existing_doc_count,
            "total_docs_in_topics": 0,
            "remaining_doc_count": 0,
            "topics": {},
        }
        os.makedirs(VOLUME_DIR, exist_ok=True)
        write_json_file(output_path, volume_data)
        return (True, "Created (no docs needed)", volume_data, False)

    # Get source-specific context
    source_tree = get_source_tree(source_type)
    agents_md_contents = get_agents_md_for_source(source_type)

    # Build the initial prompt (target accounts for pre-existing docs)
    prompt = TASKS_PROMPT.format(
        target_data_source=source_type,
        company_overview_md_contents=company_overview,
        initiatives_md_contents=initiatives,
        source_list=source_list,
        source_tree_contents=source_tree,
        agents_md_contents=agents_md_contents,
        target_volume=effective_target,
    )

    # Initialize LLM (no tools needed)
    llm = get_llm(tools=None, quiet=quiet)

    messages: list[Message] = [
        Message(role="user", content=prompt),
    ]

    estimation_failed = False
    json_str = ""

    try:
        for attempt in range(max_attempts):
            response = ""

            # Generate the response
            for chunk in llm.generate(messages):
                if isinstance(chunk, str):
                    response += chunk

            # Add assistant response to messages for potential follow-up
            messages.append(Message(role="assistant", content=response))

            # Extract and validate JSON
            json_str = extract_json_from_response(response)
            validation_error = validate_volume_json(json_str)

            if validation_error:
                return (False, f"Validation error: {validation_error}", None, False)

            # Check estimation accuracy
            estimated_total = get_total_from_json(json_str)
            is_accurate, off_percentage = check_estimation_accuracy(
                estimated_total, effective_target
            )

            if is_accurate:
                # Estimation is within tolerance
                break

            # Estimation is off - retry if we have attempts left
            if attempt < max_attempts - 1:
                correction_prompt = ESTIMATION_OFF_PROMPT.format(
                    estimated_total_docs=estimated_total,
                    source_type=source_type,
                    actual_total_docs=effective_target,
                    estimation_off_percentage=round(off_percentage, 1),
                )
                messages.append(Message(role="user", content=correction_prompt))
            else:
                # Out of attempts, mark as failed but still save
                estimation_failed = True

        # Normalize and save with pre-existing doc count
        volume_data = normalize_volume_json(json_str, pre_existing_doc_count)

        os.makedirs(VOLUME_DIR, exist_ok=True)
        write_json_file(output_path, volume_data)

        status = "Created (estimation off)" if estimation_failed else "Created"
        return (True, status, volume_data, estimation_failed)

    except Exception as e:
        return (False, f"Error: {e}", None, False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate volume task documents per source type."
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=5,
        help="Number of source types to process in parallel (default: 5)",
    )
    args = parser.parse_args()

    print("Step 9: Generate Volume Documents")
    print("=" * 40)
    print("This script generates volume task documents for each source type.")
    print("Each document contains topics and their target document counts.")
    print("Target volume is extracted from each source's agents.md file.")
    print(f"Output directory: {VOLUME_DIR}")
    print()

    # Get all source types
    source_types = get_source_types()

    if not source_types:
        print("No source types found. Run step 4 first.")
        return

    print(f"Found {len(source_types)} source types: {', '.join(source_types)}")
    print(f"Parallelism: {args.parallelism}")
    print()

    # Load context files
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    initiatives = load_file(INITIATIVES_PATH)
    source_list = "\n".join(f"- {s}" for s in source_types)

    # Check which need processing
    pending = []
    skipped = 0
    for source_type in source_types:
        output_path = os.path.join(VOLUME_DIR, f"{source_type}.json")
        if os.path.exists(output_path):
            skipped += 1
        else:
            pending.append(source_type)

    print(f"Pending: {len(pending)} to generate, {skipped} already exist.")
    print()

    if not pending:
        print("All volume documents already generated.")
        _print_statistics()
        return

    succeeded = 0
    failed = 0
    errors: list[tuple[str, str]] = []
    estimation_warnings: list[str] = []

    if args.parallelism <= 1:
        # Sequential processing
        for source_type in tqdm(pending, desc="Processing sources"):
            success, message, _data, estimation_failed = generate_volume_for_source(
                source_type=source_type,
                company_overview=company_overview,
                initiatives=initiatives,
                source_list=source_list,
                quiet=False,
            )
            if success:
                succeeded += 1
                if estimation_failed:
                    estimation_warnings.append(source_type)
            else:
                failed += 1
                errors.append((source_type, message))
                tqdm.write(f"[FAIL] {source_type}: {message}")
    else:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures = {
                executor.submit(
                    generate_volume_for_source,
                    source_type,
                    company_overview,
                    initiatives,
                    source_list,
                    True,  # quiet=True for parallel
                ): source_type
                for source_type in pending
            }

            with tqdm(total=len(pending), desc="Processing sources") as pbar:
                for future in as_completed(futures):
                    source_type = futures[future]
                    try:
                        success, message, _data, estimation_failed = future.result()
                        if success:
                            succeeded += 1
                            if estimation_failed:
                                estimation_warnings.append(source_type)
                        else:
                            failed += 1
                            errors.append((source_type, message))
                            tqdm.write(f"[FAIL] {source_type}: {message}")
                    except Exception as e:
                        failed += 1
                        errors.append((source_type, str(e)))
                        tqdm.write(f"[FAIL] {source_type}: {e}")
                    pbar.update(1)

    # Summary
    print()
    print("=" * 40)
    print(f"Generation complete. {succeeded} created, {skipped} skipped, {failed} failed.")

    if errors:
        print()
        print(f"Errors ({len(errors)}):")
        for source_type, error in errors:
            print(f"  - {source_type}: {error}")

    if estimation_warnings:
        print()
        print("=" * 40)
        print(f"WARNING: {len(estimation_warnings)} source(s) have inaccurate estimations (>10% off):")
        for source_type in estimation_warnings:
            print(f"  - {source_type}")
        print()
        print("You may want to manually review and adjust the volume files for these sources.")
        print(f"Volume files are located in: {VOLUME_DIR}")

    # Print and update statistics
    _print_statistics()
    _update_statistics()


def _print_statistics() -> None:
    """Print statistics about generated volume documents."""
    if not os.path.exists(VOLUME_DIR):
        return

    print()
    print("=" * 40)
    print("Volume Document Statistics")
    print("=" * 40)

    total_topics = 0
    total_target_docs = 0
    total_existing = 0
    total_remaining = 0

    for filename in sorted(os.listdir(VOLUME_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(VOLUME_DIR, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
            source_name = filename.replace(".json", "")
            topics = data.get("topics", {})
            topic_count = len(topics)
            doc_count = data.get("total_docs_in_topics", sum(t["desired"] for t in topics.values()))
            existing = data.get("pre_existing_doc_count", 0)
            remaining = data.get("remaining_doc_count", doc_count)
            total_topics += topic_count
            total_target_docs += doc_count
            total_existing += existing
            total_remaining += remaining
            print(f"  {source_name}: {topic_count} topics, {doc_count} target, {existing} existing, {remaining} remaining")
        except Exception:
            pass

    print()
    print(f"Total: {total_topics} topics, {total_target_docs} target, {total_existing} existing, {total_remaining} remaining")


def _update_statistics() -> None:
    """Update aggregate statistics."""
    if not os.path.exists(VOLUME_DIR):
        return

    source_summaries: dict[str, dict[str, int]] = {}
    total_topics = 0
    total_target_docs = 0
    total_existing = 0
    total_remaining = 0

    for filename in sorted(os.listdir(VOLUME_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(VOLUME_DIR, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
            source_name = filename.replace(".json", "")
            topics = data.get("topics", {})
            topic_count = len(topics)
            doc_count = data.get("total_docs_in_topics", sum(t["desired"] for t in topics.values()))
            existing = data.get("pre_existing_doc_count", 0)
            remaining = data.get("remaining_doc_count", doc_count)
            total_topics += topic_count
            total_target_docs += doc_count
            total_existing += existing
            total_remaining += remaining
            source_summaries[source_name] = {
                "topics": topic_count,
                "target_documents": doc_count,
                "existing_documents": existing,
                "remaining_documents": remaining,
            }
        except Exception:
            pass

    update_statistics("Step 9: Volume Tasks", {
        "total_source_types": len(source_summaries),
        "total_topics": total_topics,
        "total_target_documents": total_target_docs,
        "total_existing_documents": total_existing,
        "total_remaining_documents": total_remaining,
        "per_source": source_summaries,
    })


if __name__ == "__main__":
    main()
