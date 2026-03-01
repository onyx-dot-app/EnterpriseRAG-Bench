"""Script for generating volume task documents per source type."""

import argparse
import json
import os
import random
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.llm import Message, get_cheap_llm, get_llm, run_auto_conversation
from src.paths import (
    AGENTS_MD_FILE,
    COMPANY_OVERVIEW_PATH,
    INITIATIVES_PATH,
    SOURCES_DIR,
    VOLUME_DIR,
)
from src.prompts.json_recovery import JSON_RECOVERY_PROMPT
from src.prompts.volume_generation import (
    CONFLICT_PROMPT,
    DOCUMENT_GENERATION_PROMPT,
    DOCUMENT_GENERATION_USER_PROMPT,
    ESTIMATION_OFF_PROMPT,
    ESTIMATION_OFF_PROMPT_SUB_TOPICS,
    RECURSIVE_TOPIC_GENERATION_PROMPT,
    TASKS_PROMPT,
    TOTAL_DOCS_PROMPT,
)
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import WriteTool
from src.utils import (
    add_dataset_doc_uuid,
    confirm_yes_no,
    extract_json_from_response,
    label_single_document,
    load_file,
    validate_no_nested_dicts,
)
from src.utils.file_io import load_json_file, write_json_file
from src.utils.statistics import update_statistics


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


# =============================================================================
# Phase 2: Recursive Topic Splitting
# =============================================================================

MAX_TOPIC_SIZE = 500


def split_topic(
    topic_name: str,
    topic_count: int,
    source_type: str,
    company_overview: str,
    source_tree: str,
    agents_md_contents: str,
    quiet: bool = False,
    max_attempts: int = 5,
) -> tuple[list[dict], bool]:
    """
    Split a single topic into smaller sub-topics using LLM.

    Args:
        topic_name: Name of the topic to split.
        topic_count: Desired document count for the topic.
        source_type: Name of the source type.
        company_overview: Company overview content.
        source_tree: Directory tree for the source.
        agents_md_contents: Formatted agents.md contents.
        quiet: If True, suppress LLM status output.
        max_attempts: Maximum attempts to get accurate split.

    Returns:
        (sub_topics, estimation_failed) tuple where sub_topics is a list of
        {"name": str, "desired": int, "completed": 0} dicts.
    """
    prompt = RECURSIVE_TOPIC_GENERATION_PROMPT.format(
        company_overview=company_overview,
        target_data_source=source_type,
        source_tree_contents=source_tree,
        agents_md_contents=agents_md_contents,
        original_topic=topic_name,
        original_count=topic_count,
    )

    llm = get_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    estimation_failed = False

    for attempt in range(max_attempts):
        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                response += chunk

        messages.append(Message(role="assistant", content=response))

        try:
            json_str = extract_json_from_response(response)
            data = json.loads(json_str)

            # Handle the expected format: {"topics": [{"name": count}, ...]}
            topics_list = data.get("topics", [])
            if not topics_list:
                continue

            # Parse sub-topics
            sub_topics = []
            total = 0
            for topic_entry in topics_list:
                for name, count in topic_entry.items():
                    count_int = int(count)
                    sub_topics.append({
                        "name": name,
                        "desired": count_int,
                        "completed": 0,
                    })
                    total += count_int

            # Check estimation accuracy
            is_accurate, off_percentage = check_estimation_accuracy(total, topic_count)

            if is_accurate:
                return (sub_topics, False)

            # Retry if inaccurate
            if attempt < max_attempts - 1:
                correction = ESTIMATION_OFF_PROMPT_SUB_TOPICS.format(
                    estimated_total_docs=total,
                    original_count=topic_count,
                    estimation_off_percentage=round(off_percentage, 1),
                )
                messages.append(Message(role="user", content=correction))
            else:
                estimation_failed = True
                return (sub_topics, estimation_failed)

        except Exception:
            if attempt == max_attempts - 1:
                # Return original topic as single sub-topic on failure
                return ([{"name": topic_name, "desired": topic_count, "completed": 0}], True)

    # Fallback: return original topic
    return ([{"name": topic_name, "desired": topic_count, "completed": 0}], True)


def recursively_split_topics(
    topics: dict[str, dict],
    source_type: str,
    company_overview: str,
    source_tree: str,
    agents_md_contents: str,
    quiet: bool = False,
) -> tuple[dict[str, dict], list[str]]:
    """
    Recursively split all topics larger than MAX_TOPIC_SIZE.

    Sub-topics are nested under the original topic with a "sub_topics" key.

    Args:
        topics: Current topics dict {name: {"desired": int, "completed": int, "sub_topics"?: {...}}}.
        source_type: Name of the source type.
        company_overview: Company overview content.
        source_tree: Directory tree for the source.
        agents_md_contents: Formatted agents.md contents.
        quiet: If True, suppress LLM status output.

    Returns:
        (new_topics, warnings) tuple where warnings is list of topic names
        that had estimation issues.
    """
    warnings = []
    result_topics = {}

    for topic_name, topic_data in topics.items():
        desired = topic_data.get("desired", 0)
        completed = topic_data.get("completed", 0)
        has_sub_topics = "sub_topics" in topic_data

        if desired <= MAX_TOPIC_SIZE or has_sub_topics:
            # Topic is small enough or already split, keep as-is
            result_topics[topic_name] = topic_data
        else:
            # Split this topic
            sub_topics, estimation_failed = split_topic(
                topic_name=topic_name,
                topic_count=desired,
                source_type=source_type,
                company_overview=company_overview,
                source_tree=source_tree,
                agents_md_contents=agents_md_contents,
                quiet=quiet,
            )

            if estimation_failed:
                warnings.append(topic_name)

            # Convert sub_topics list to dict
            sub_topics_dict = {
                st["name"]: {"desired": st["desired"], "completed": st["completed"]}
                for st in sub_topics
            }

            # Recursively split any sub-topics that are still too large
            split_sub_topics, sub_warnings = recursively_split_topics(
                topics=sub_topics_dict,
                source_type=source_type,
                company_overview=company_overview,
                source_tree=source_tree,
                agents_md_contents=agents_md_contents,
                quiet=quiet,
            )

            warnings.extend(sub_warnings)

            # Nest sub-topics under the original topic
            result_topics[topic_name] = {
                "desired": desired,
                "completed": completed,
                "sub_topics": split_sub_topics,
            }

    return (result_topics, warnings)


def _needs_splitting(topic_data: dict) -> bool:
    """Check if a topic needs splitting (large and not already split)."""
    desired = topic_data.get("desired", 0)
    has_sub_topics = "sub_topics" in topic_data
    return desired > MAX_TOPIC_SIZE and not has_sub_topics


def split_large_topics_for_source(
    source_type: str,
    company_overview: str,
    quiet: bool = False,
) -> tuple[bool, str, list[str]]:
    """
    Split large topics for a single source type.

    Args:
        source_type: Name of the source type.
        company_overview: Company overview content.
        quiet: If True, suppress LLM status output.

    Returns:
        (modified, message, warnings) tuple.
    """
    filepath = os.path.join(VOLUME_DIR, f"{source_type}.json")
    if not os.path.exists(filepath):
        return (False, "File not found", [])

    try:
        with open(filepath) as f:
            data = json.load(f)
    except Exception as e:
        return (False, f"Error loading: {e}", [])

    topics = data.get("topics", {})
    if not topics:
        return (False, "No topics", [])

    # Check if any topics need splitting (large and not already split)
    large_topics = [name for name, t in topics.items() if _needs_splitting(t)]
    if not large_topics:
        return (False, "No large topics", [])

    # Get source context
    source_tree = get_source_tree(source_type)
    agents_md_contents = get_agents_md_for_source(source_type)

    # Recursively split
    new_topics, warnings = recursively_split_topics(
        topics=topics,
        source_type=source_type,
        company_overview=company_overview,
        source_tree=source_tree,
        agents_md_contents=agents_md_contents,
        quiet=quiet,
    )

    # Update the data
    data["topics"] = new_topics
    data["total_docs_in_topics"] = sum(t["desired"] for t in new_topics.values())
    data["remaining_doc_count"] = max(
        0, data["total_docs_in_topics"] - data.get("pre_existing_doc_count", 0)
    )

    # Write back
    write_json_file(filepath, data)

    return (True, f"Split {len(large_topics)} large topic(s)", warnings)


def split_large_topics(company_overview: str, parallelism: int = 1) -> list[str]:
    """
    Phase 2: Split large topics (>500) across all sources.

    Args:
        company_overview: Company overview content.
        parallelism: Number of sources to process in parallel.

    Returns:
        List of source types that had estimation warnings.
    """
    print()
    print("=" * 40)
    print(f"Phase 2: Split Large Topics (>{MAX_TOPIC_SIZE} docs)")
    print("=" * 40)
    print()
    print("Note: Depending on the volume of documents, this phase may take some time")
    print("      as it recursively splits topics until all are under 500 docs.")
    print()

    if not os.path.exists(VOLUME_DIR):
        print("No volume directory found.")
        return []

    # Find sources with large topics (that haven't been split yet)
    sources_to_process = []
    for filename in sorted(os.listdir(VOLUME_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(VOLUME_DIR, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
            topics = data.get("topics", {})
            large_count = sum(1 for t in topics.values() if _needs_splitting(t))
            if large_count > 0:
                source_name = filename.replace(".json", "")
                sources_to_process.append((source_name, large_count))
        except Exception:
            pass

    if not sources_to_process:
        print("No sources have topics larger than 500 documents.")
        return []

    total_large = sum(count for _, count in sources_to_process)
    print(f"Found {len(sources_to_process)} source(s) with {total_large} large topic(s).")
    print()

    all_warnings: list[str] = []

    if parallelism <= 1:
        # Sequential processing
        for source_type, large_count in tqdm(sources_to_process, desc="Splitting topics"):
            modified, message, warnings = split_large_topics_for_source(
                source_type=source_type,
                company_overview=company_overview,
                quiet=False,
            )
            if warnings:
                all_warnings.extend([f"{source_type}/{w}" for w in warnings])
    else:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = {
                executor.submit(
                    split_large_topics_for_source,
                    source_type,
                    company_overview,
                    True,  # quiet=True for parallel
                ): source_type
                for source_type, _ in sources_to_process
            }

            with tqdm(total=len(sources_to_process), desc="Splitting topics") as pbar:
                for future in as_completed(futures):
                    source_type = futures[future]
                    try:
                        modified, message, warnings = future.result()
                        if warnings:
                            all_warnings.extend([f"{source_type}/{w}" for w in warnings])
                    except Exception as e:
                        tqdm.write(f"[FAIL] {source_type}: {e}")
                    pbar.update(1)

    # Check if any topics still need splitting (not yet split)
    still_large = []
    for filename in sorted(os.listdir(VOLUME_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(VOLUME_DIR, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
            topics = data.get("topics", {})
            for name, t in topics.items():
                if _needs_splitting(t):
                    source_name = filename.replace(".json", "")
                    still_large.append(f"{source_name}/{name}")
        except Exception:
            pass

    if still_large:
        print()
        print(f"WARNING: {len(still_large)} topic(s) still exceed {MAX_TOPIC_SIZE} docs:")
        for topic in still_large[:10]:
            print(f"  - {topic}")
        if len(still_large) > 10:
            print(f"  ... and {len(still_large) - 10} more")

    print()
    print("Phase 2 complete.")
    print()
    print("=" * 40)
    print("Please review the generated volume files to ensure you're happy with the")
    print("topic breakdown. You can make manual modifications if needed.")
    print(f"Volume files are located in: {VOLUME_DIR}")
    print()
    print("If you want to make changes, you can exit now and rerun the script later")
    print("to continue from where you left off.")
    print()

    if not confirm_yes_no("Do you want to continue?", retry_on_invalid=True):
        print("Exiting. You can rerun the script later to continue.")
        raise SystemExit(0)

    return all_warnings


# =============================================================================
# Phase 3: Document Generation
# =============================================================================

# Global lock for volume file updates
_volume_locks: dict[str, threading.Lock] = {}
_volume_locks_lock = threading.Lock()


def _get_volume_lock(source_type: str) -> threading.Lock:
    """Get or create a lock for a specific source type's volume file."""
    with _volume_locks_lock:
        if source_type not in _volume_locks:
            _volume_locks[source_type] = threading.Lock()
        return _volume_locks[source_type]


class TrackingWriteTool(WriteTool):
    """WriteTool that tracks written file paths and prevents overwrites."""

    def __init__(self, base_dir: str | None = None, allow_create_dirs: bool = False) -> None:
        super().__init__(base_dir=base_dir, allow_create_dirs=allow_create_dirs)
        self._written_paths: list[str] = []

    @property
    def written_paths(self) -> list[str]:
        """Return list of paths written since last reset."""
        return self._written_paths.copy()

    def reset_tracking(self) -> None:
        """Clear the list of written paths."""
        self._written_paths = []

    def execute(self, content: str, file_path: str = "") -> str:
        """Write content and track the path. Returns error if file exists."""
        # Check if file already exists before writing
        if self._base_dir and file_path:
            normalized_path = self._normalize_path(file_path)
            target_path = os.path.join(self._base_dir, normalized_path)
            if os.path.exists(target_path):
                return f"Error: File already exists at {file_path}. {CONFLICT_PROMPT}"

        result = super().execute(content, file_path)
        if result.startswith("Successfully wrote to "):
            # Extract the actual written path
            actual_path = result.replace("Successfully wrote to ", "")
            self._written_paths.append(actual_path)
        return result


def collect_leaf_topics(
    topics: dict[str, dict],
    topic_path: str = "",
) -> list[tuple[str, list[str], int, int]]:
    """
    Recursively collect all leaf topics that need documents.

    Args:
        topics: Topics dict from volume JSON.
        topic_path: Current path (for nested topics).

    Returns:
        List of (topic_full_path, topic_path_parts, desired, completed) tuples.
        Only returns topics where desired > completed.
    """
    result = []

    for topic_name, topic_data in topics.items():
        current_path = f"{topic_path} => {topic_name}" if topic_path else topic_name
        path_parts = current_path.split(" => ")

        if "sub_topics" in topic_data:
            # Recurse into sub_topics
            result.extend(collect_leaf_topics(topic_data["sub_topics"], current_path))
        else:
            # This is a leaf topic
            desired = topic_data.get("desired", 0)
            completed = topic_data.get("completed", 0)
            if desired > completed:
                result.append((current_path, path_parts, desired, completed))

    return result


def update_volume_completed(
    source_type: str,
    topic_path_parts: list[str],
    created_file_path: str,
    increment: int = 1,
) -> None:
    """
    Thread-safe update of completed count and created_files for a topic in a volume file.

    Args:
        source_type: Name of the source type.
        topic_path_parts: List of topic names to navigate (e.g., ["Parent Topic", "Child Topic"]).
        created_file_path: Path of the newly created file to add to created_files list.
        increment: Amount to increment completed count by.
    """
    lock = _get_volume_lock(source_type)
    filepath = os.path.join(VOLUME_DIR, f"{source_type}.json")

    with lock:
        try:
            data = load_json_file(filepath)
        except Exception:
            return

        # Navigate to the correct topic
        current = data.get("topics", {})
        for i, part in enumerate(topic_path_parts):
            if part not in current:
                return

            if i == len(topic_path_parts) - 1:
                # This is the leaf topic
                current[part]["completed"] = current[part].get("completed", 0) + increment
            else:
                # Navigate to sub_topics
                if "sub_topics" not in current[part]:
                    return
                current = current[part]["sub_topics"]

        # Add created file path to the top-level created_files list
        if "created_files" not in data:
            data["created_files"] = []
        data["created_files"].append(created_file_path)

        write_json_file(filepath, data)


def try_recover_json(broken_json: str, quiet: bool = True) -> str | None:
    """
    Attempt to recover broken JSON using cheap LLM.

    Args:
        broken_json: The broken JSON string.
        quiet: If True, suppress LLM output.

    Returns:
        Recovered JSON string or None if recovery failed.
    """
    prompt = JSON_RECOVERY_PROMPT.format(broken_json_string=broken_json)
    llm = get_cheap_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            response += chunk

    response = response.strip()

    # Try to parse the response
    try:
        json.loads(response)
        return response
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        try:
            extracted = extract_json_from_response(response)
            json.loads(extracted)
            return extracted
        except Exception:
            return None


def validate_and_process_document(
    file_path: str,
    quiet: bool = True,
) -> tuple[bool, str | None]:
    """
    Validate a written document with JSON recovery, then add UUID/labels if valid.

    Args:
        file_path: Path to the written JSON file.
        quiet: If True, suppress LLM output.

    Returns:
        (success, error_message) tuple.
    """
    if not os.path.exists(file_path):
        return (False, f"File not found: {file_path}")

    # Read raw content
    try:
        with open(file_path) as f:
            raw_content = f.read()
    except Exception as e:
        return (False, f"Error reading file: {e}")

    # Try to parse JSON
    data = None
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as parse_error:
        # Attempt JSON recovery
        recovered = try_recover_json(raw_content, quiet=quiet)
        if recovered:
            try:
                data = json.loads(recovered)
                # Write recovered JSON back to file
                with open(file_path, "w") as f:
                    f.write(recovered)
            except json.JSONDecodeError:
                return (False, f"JSON recovery failed: {parse_error}")
        else:
            return (False, f"Invalid JSON and recovery failed: {parse_error}")

    if data is None:
        return (False, "Failed to parse JSON")

    # Validate no nested dicts
    validation_error = validate_no_nested_dicts(data)
    if validation_error:
        return (False, f"Validation error: {validation_error}")

    # Add field labels
    label_single_document(file_path, quiet=True)

    # Add dataset_doc_uuid
    add_dataset_doc_uuid(file_path)

    return (True, None)


def get_existing_docs_for_topic(source_type: str) -> list[str]:
    """
    Get list of existing document paths from the volume JSON's created_files.

    This helps the LLM avoid creating duplicate-sounding documents.

    Args:
        source_type: Name of the source type.

    Returns:
        List of created file paths (one per line for the prompt).
    """
    lock = _get_volume_lock(source_type)
    filepath = os.path.join(VOLUME_DIR, f"{source_type}.json")

    with lock:
        try:
            data = load_json_file(filepath)
        except Exception:
            return []

        created_files = data.get("created_files", [])

    # Return a random sample to avoid overwhelming the prompt
    if len(created_files) > 50:
        return random.sample(created_files, 50)
    return created_files


def generate_single_document(
    source_type: str,
    topic_and_subtopics: str,
    topic_path_parts: list[str],
    company_overview: str,
    source_tree: str,
    agents_md_contents: str,
    quiet: bool = False,
    max_retries: int = 3,
) -> tuple[bool, str]:
    """
    Generate a single document for a topic using LLM.

    Args:
        source_type: Name of the source type.
        topic_and_subtopics: Full topic path (e.g., "Parent => Child => Leaf").
        topic_path_parts: List of topic name parts for volume update.
        company_overview: Company overview content.
        source_tree: Directory tree for the source.
        agents_md_contents: Formatted agents.md contents.
        quiet: If True, suppress LLM output.
        max_retries: Maximum retries for validation failures (restarts from scratch).

    Returns:
        (success, message) tuple.
    """
    # Get existing docs to help with diversity
    existing_docs = get_existing_docs_for_topic(source_type)
    existing_docs_str = "\n".join(existing_docs) if existing_docs else "(none yet)"

    # Build the system prompt
    system_prompt = DOCUMENT_GENERATION_PROMPT.format(
        company_overview=company_overview,
        source_type=source_tree,
        agents_md_contents=agents_md_contents,
        existing_docs=existing_docs_str,
        topic_and_subtopics=topic_and_subtopics,
    )

    # Build the user prompt
    user_prompt = DOCUMENT_GENERATION_USER_PROMPT.format(
        topic_and_subtopics=topic_and_subtopics,
    )

    for retry in range(max_retries):
        # Create fresh tools for each retry
        write_tool = TrackingWriteTool(base_dir=SOURCES_DIR, allow_create_dirs=False)

        # Initialize cheap LLM with only the write tool
        llm = get_cheap_llm(
            tools=[write_tool.schema],
            quiet=quiet,
        )

        # Create tool runner
        tool_runner = ToolRunner()
        tool_runner.register(write_tool)

        # Build fresh messages for each retry
        messages: list[Message] = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            # Run auto conversation until document is written
            run_auto_conversation(
                llm=llm,
                tool_runner=tool_runner,
                messages=messages,
                max_tool_cycles=10,
                max_iterations=30,
                quiet=quiet,
            )

            # Check if a document was written
            if not write_tool.written_paths:
                # No document written, retry from beginning
                continue

            # Validate the written document (with JSON recovery if needed)
            file_path = write_tool.written_paths[0]
            success, error = validate_and_process_document(file_path, quiet=quiet)

            if not success:
                # Delete invalid file and retry from beginning
                if os.path.exists(file_path):
                    os.remove(file_path)
                continue

            # Validation passed! Update the volume completed count and add file path
            update_volume_completed(source_type, topic_path_parts, file_path, 1)
            return (True, f"Created {file_path}")

        except Exception as e:
            # On exception, clean up any written files and retry
            for path in write_tool.written_paths:
                if os.path.exists(path):
                    os.remove(path)
            if retry == max_retries - 1:
                return (False, f"Error: {e}")

    return (False, "Max retries exceeded without creating valid document")


def generate_documents_for_source(
    source_type: str,
    company_overview: str,
    parallelism: int = 1,
    quiet: bool = False,
) -> tuple[int, int, list[str]]:
    """
    Generate all pending documents for a single source type.

    Args:
        source_type: Name of the source type.
        company_overview: Company overview content.
        parallelism: Number of documents to generate in parallel.
        quiet: If True, suppress LLM output.

    Returns:
        (success_count, fail_count, errors) tuple.
    """
    filepath = os.path.join(VOLUME_DIR, f"{source_type}.json")
    if not os.path.exists(filepath):
        return (0, 0, ["Volume file not found"])

    try:
        data = load_json_file(filepath)
    except Exception as e:
        return (0, 0, [f"Error loading volume file: {e}"])

    topics = data.get("topics", {})
    if not topics:
        return (0, 0, [])

    # Get source context
    source_tree = get_source_tree(source_type)
    agents_md_contents = get_agents_md_for_source(source_type)

    # Collect all leaf topics needing documents
    leaf_topics = collect_leaf_topics(topics)
    if not leaf_topics:
        return (0, 0, [])

    # Calculate total documents needed
    total_needed = sum(desired - completed for _, _, desired, completed in leaf_topics)
    if total_needed == 0:
        return (0, 0, [])

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    # Build work items: (topic_path, topic_parts, docs_to_create)
    work_items = []
    for topic_path, topic_parts, desired, completed in leaf_topics:
        docs_to_create = desired - completed
        for _ in range(docs_to_create):
            work_items.append((topic_path, topic_parts))

    if parallelism <= 1:
        # Sequential processing
        for topic_path, topic_parts in tqdm(
            work_items,
            desc=f"Generating docs for {source_type}",
            leave=False,
        ):
            success, message = generate_single_document(
                source_type=source_type,
                topic_and_subtopics=topic_path,
                topic_path_parts=topic_parts,
                company_overview=company_overview,
                source_tree=source_tree,
                agents_md_contents=agents_md_contents,
                quiet=quiet,
            )
            if success:
                success_count += 1
            else:
                fail_count += 1
                errors.append(f"{topic_path}: {message}")
    else:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = {
                executor.submit(
                    generate_single_document,
                    source_type,
                    topic_path,
                    topic_parts,
                    company_overview,
                    source_tree,
                    agents_md_contents,
                    True,  # quiet=True for parallel
                ): topic_path
                for topic_path, topic_parts in work_items
            }

            with tqdm(
                total=len(work_items),
                desc=f"Generating docs for {source_type}",
                leave=False,
            ) as pbar:
                for future in as_completed(futures):
                    topic_path = futures[future]
                    try:
                        success, message = future.result()
                        if success:
                            success_count += 1
                        else:
                            fail_count += 1
                            errors.append(f"{topic_path}: {message}")
                    except Exception as e:
                        fail_count += 1
                        errors.append(f"{topic_path}: {e}")
                    pbar.update(1)

    return (success_count, fail_count, errors)


def generate_documents(company_overview: str, parallelism: int = 10) -> None:
    """
    Phase 3: Generate documents for all sources based on volume files.

    Args:
        company_overview: Company overview content.
        parallelism: Number of documents to generate in parallel per source.
    """
    print()
    print("=" * 40)
    print("Phase 3: Generate Volume Documents")
    print("=" * 40)
    print()
    print("Note: This phase generates the actual documents based on the topics")
    print("      in the volume files. This may take a long time depending on")
    print("      the total number of documents to generate.")
    print()

    if not os.path.exists(VOLUME_DIR):
        print("No volume directory found.")
        return

    # Collect sources with pending documents
    sources_with_pending = []
    total_pending = 0

    for filename in sorted(os.listdir(VOLUME_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(VOLUME_DIR, filename)
        try:
            data = load_json_file(filepath)
            topics = data.get("topics", {})
            leaf_topics = collect_leaf_topics(topics)
            pending = sum(desired - completed for _, _, desired, completed in leaf_topics)
            if pending > 0:
                source_name = filename.replace(".json", "")
                sources_with_pending.append((source_name, pending))
                total_pending += pending
        except Exception:
            pass

    if not sources_with_pending:
        print("No sources have pending documents to generate.")
        return

    print(f"Found {len(sources_with_pending)} source(s) with {total_pending} pending document(s):")
    for source_name, pending in sources_with_pending:
        print(f"  - {source_name}: {pending} documents")
    print()

    total_success = 0
    total_fail = 0
    all_errors: list[str] = []

    for source_type, pending_count in sources_with_pending:
        print(f"\nProcessing {source_type} ({pending_count} documents)...")

        success, fail, errors = generate_documents_for_source(
            source_type=source_type,
            company_overview=company_overview,
            parallelism=parallelism,
            quiet=True,
        )

        total_success += success
        total_fail += fail
        all_errors.extend([f"{source_type}/{e}" for e in errors])

        print(f"  Created: {success}, Failed: {fail}")

    print()
    print("=" * 40)
    print("Phase 3 Summary")
    print("=" * 40)
    print(f"Total documents created: {total_success}")
    print(f"Total failures: {total_fail}")

    if all_errors and len(all_errors) <= 20:
        print()
        print("Errors:")
        for error in all_errors:
            print(f"  - {error}")
    elif all_errors:
        print()
        print(f"Errors ({len(all_errors)} total, showing first 20):")
        for error in all_errors[:20]:
            print(f"  - {error}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate volume task documents per source type."
    )
    parser.add_argument(
        "--source-parallelism",
        type=int,
        default=5,
        help="Number of source types to process in parallel in Phase 1 (default: 5)",
    )
    parser.add_argument(
        "--topic-parallelism",
        type=int,
        default=5,
        help="Number of topics to expand in parallel in Phase 2 (default: 5)",
    )
    parser.add_argument(
        "--doc-parallelism",
        type=int,
        default=10,
        help="Number of documents to generate in parallel in Phase 3 (default: 10)",
    )
    args = parser.parse_args()

    print("Step 9: Generate Volume Documents")
    print("=" * 40)
    print("This script generates volume task documents for each source type.")
    print("Phase 1: Generate topics and document counts per source")
    print("Phase 2: Split large topics (>500 docs) into smaller sub-topics")
    print("Phase 3: Generate actual documents based on the topics")
    print()
    print("Target volume is extracted from each source's agents.md file.")
    print(f"Output directory: {VOLUME_DIR}")
    print()

    # Get all source types
    source_types = get_source_types()

    if not source_types:
        print("No source types found. Run step 4 first.")
        return

    print(f"Found {len(source_types)} source types: {', '.join(source_types)}")
    print(f"Source parallelism: {args.source_parallelism}")
    print(f"Topic parallelism: {args.topic_parallelism}")
    print(f"Document parallelism: {args.doc_parallelism}")
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

    print()
    print("=" * 40)
    print("Phase 1: Generate Volume Documents")
    print("=" * 40)

    estimation_warnings: list[str] = []

    if not pending:
        print("All volume documents already generated.")
    else:
        succeeded = 0
        failed = 0
        errors: list[tuple[str, str]] = []

        if args.source_parallelism <= 1:
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
            with ThreadPoolExecutor(max_workers=args.source_parallelism) as executor:
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

        # Phase 1 Summary
        print()
        print(f"Phase 1 complete. {succeeded} created, {skipped} skipped, {failed} failed.")

        if errors:
            print()
            print(f"Errors ({len(errors)}):")
            for source_type, error in errors:
                print(f"  - {source_type}: {error}")

    # Phase 2: Split large topics
    split_warnings = split_large_topics(
        company_overview=company_overview,
        parallelism=args.topic_parallelism,
    )
    estimation_warnings.extend(split_warnings)

    # Phase 3: Generate actual documents
    generate_documents(
        company_overview=company_overview,
        parallelism=args.doc_parallelism,
    )

    # Final warnings
    if estimation_warnings:
        print()
        print("=" * 40)
        print(f"WARNING: {len(estimation_warnings)} topic(s) have inaccurate estimations (>10% off):")
        for warning in estimation_warnings[:20]:
            print(f"  - {warning}")
        if len(estimation_warnings) > 20:
            print(f"  ... and {len(estimation_warnings) - 20} more")
        print()
        print("You may want to manually review and adjust the volume files.")
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
