"""Script to shuffle documents using LLM-chosen neighboring directories.

Unlike step 1 (pure random), this uses an LLM to pick a plausible but non-ideal
directory for each selected document within the same source type. This better matches
real-world noise where misfiled documents are biased toward local structure (adjacent
or parent/child directories). Files are processed in parallel across all source types.

Usage:
    python -m src.scripts.data_gen_stage_2_add_noise.step_2_llm_based_shuffle [OPTIONS]

Args:
    --percentage   Percentage of documents to shuffle within each source type (default: 3.0)
    --parallelism  Number of files to process in parallel (default: 50)
"""

import argparse
import os
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from src.llm import Message, get_cheap_llm
from src.paths import SOURCES_DIR, SOURCE_TREE_PATH
from src.prompts.neighboring_shuffle import PATH_ERROR_RESPONSE, SHUFFLE_PROMPT
from src.utils.directory_tree import get_directory_tree
from src.utils.field_ordering import load_file_without_metadata
from src.utils.file_io import load_file, load_json_file, write_json_file
from src.utils.file_selection import is_noise_document
from src.utils.statistics import update_statistics

STEP_OVERVIEW = """\
Uses an LLM to pick plausible but non-ideal directories for selected documents.
Unlike random shuffle, misfiled documents are biased toward local structure
(adjacent or parent/child directories). Previously shuffled documents are excluded.

Shuffling {{percentage}}% of documents per source type.
Parallelism: {{parallelism}}
"""


# =============================================================================
# Source Tree
# =============================================================================


def get_source_tree() -> str:
    """Get the full directory tree for all sources.

    Returns:
        Tree output string for the sources directory.
    """
    if os.path.exists(SOURCE_TREE_PATH):
        return load_file(SOURCE_TREE_PATH)
    return get_directory_tree(SOURCES_DIR)


def get_source_type_tree(source_type: str) -> str:
    """Get the directory tree for a single source type.

    Args:
        source_type: Name of the source type (e.g. "confluence").

    Returns:
        Tree output string for that source type.
    """
    source_type_dir = os.path.join(SOURCES_DIR, source_type)
    return get_directory_tree(source_type_dir)


# =============================================================================
# File Collection
# =============================================================================


def collect_json_files(source_type_dir: str) -> list[str]:
    """Collect all JSON file paths under a source type directory.

    Args:
        source_type_dir: Absolute path to a source type directory.

    Returns:
        List of absolute paths to JSON files.
    """
    json_files: list[str] = []
    for root, _dirs, files in os.walk(source_type_dir):
        for filename in files:
            if filename.endswith(".json"):
                json_files.append(os.path.join(root, filename))
    return json_files


# =============================================================================
# LLM-based Directory Selection
# =============================================================================


def validate_proposed_dir(proposed_dir: str, source_type: str) -> str | None:
    """Validate that a proposed directory exists under the source type.

    Checks the path as-is first (expecting source_type/... format), then
    falls back to prepending the source type directory in case the LLM
    omitted it.

    Args:
        proposed_dir: The LLM's proposed directory path.
        source_type: Name of the source type.

    Returns:
        Absolute path to the directory if valid, None otherwise.
    """
    cleaned = proposed_dir.strip("`\"' \n/")

    # Strip leading "sources/" if present (we only store under SOURCES_DIR)
    if cleaned.startswith("sources/"):
        cleaned = cleaned[len("sources/") :]

    source_type_dir = os.path.join(SOURCES_DIR, source_type)

    # First: check if path already includes the source type prefix
    # (e.g. "confluence/eng-infra/some-topic")
    abs_with_sources = os.path.join(SOURCES_DIR, cleaned)
    if cleaned.startswith(f"{source_type}/") or cleaned == source_type:
        if os.path.isdir(abs_with_sources):
            return abs_with_sources

    # Fallback: treat as relative to the source type directory
    # (e.g. "eng-infra/some-topic" -> SOURCES_DIR/confluence/eng-infra/some-topic)
    abs_with_prefix = os.path.join(source_type_dir, cleaned)
    if os.path.isdir(abs_with_prefix):
        return abs_with_prefix

    return None


def pick_directory_with_llm(
    file_path: str,
    file_contents: str,
    source_type: str,
    source_tree: str,
    max_attempts: int = 5,
) -> str | None:
    """Use the LLM to pick a new directory for a document.

    Args:
        file_path: Path to the file relative to the source type dir.
        file_contents: The document's JSON content as a string.
        source_type: Name of the source type.
        source_tree: Directory tree string for the source type.
        max_attempts: Maximum retries before giving up.

    Returns:
        Absolute path to the chosen directory, or None on failure.
    """
    # Include source type in the path shown to the LLM
    file_path_with_source = f"{source_type}/{file_path}"

    prompt = SHUFFLE_PROMPT.format(
        file_path=file_path_with_source,
        file_contents=file_contents,
        source_directory_structure=source_tree,
    )

    llm = get_cheap_llm(tools=None, quiet=True)
    messages: list[Message] = [Message(role="user", content=prompt)]

    for attempt in range(max_attempts):
        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                response += chunk

        abs_dir = validate_proposed_dir(response.strip(), source_type)
        if abs_dir is not None:
            # Make sure it's different from the file's current directory
            current_dir = os.path.dirname(
                os.path.join(SOURCES_DIR, source_type, file_path)
            )
            if abs_dir != current_dir:
                return abs_dir

        if attempt < max_attempts - 1:
            messages.append(Message(role="assistant", content=response.strip()))
            messages.append(Message(role="user", content=PATH_ERROR_RESPONSE))

    return None


# =============================================================================
# Move & Tag
# =============================================================================


def move_and_tag_file(
    file_path_abs: str,
    dest_dir: str,
    source_type: str,
) -> str | None:
    """Move a JSON file to a new directory and add original_location field.

    The original_location field is inserted before dataset_doc_uuid so that
    dataset_doc_uuid remains the last field.

    Args:
        file_path_abs: Absolute path to the JSON file.
        dest_dir: Absolute path to the destination directory.
        source_type: Name of the source type (e.g. "confluence").

    Returns:
        The new absolute path on success, or None on failure.
    """
    source_type_dir = os.path.join(SOURCES_DIR, source_type)
    rel_from_source_type = os.path.relpath(file_path_abs, source_type_dir)
    original_location = f"{source_type}/{rel_from_source_type}"

    try:
        data = load_json_file(file_path_abs)
    except Exception as e:
        print(f"    Error loading {file_path_abs}: {e}")
        return None

    # Insert original_location before dataset_doc_uuid (which should stay last)
    if "dataset_doc_uuid" in data:
        uuid_value = data.pop("dataset_doc_uuid")
        data["original_location"] = original_location
        data["dataset_doc_uuid"] = uuid_value
    else:
        data["original_location"] = original_location

    # Determine new path, handling collisions
    filename = os.path.basename(file_path_abs)
    new_path = os.path.join(dest_dir, filename)

    if os.path.exists(new_path):
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(new_path):
            new_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
            counter += 1

    try:
        write_json_file(new_path, data)
        os.remove(file_path_abs)
    except Exception as e:
        print(f"    Error moving file: {e}")
        return None

    return new_path


# =============================================================================
# Single File Processing (unit of parallel work)
# =============================================================================


@dataclass
class ShuffleTask:
    """A single file to be shuffled."""

    file_path_abs: str
    source_type: str
    source_tree: str


@dataclass
class ShuffleResult:
    """Result of processing a single shuffle task."""

    source_type: str
    rel_original: str
    rel_new: str | None
    error: str | None


def process_single_file(task: ShuffleTask) -> ShuffleResult:
    """Process a single file: ask LLM for destination, then move it.

    Args:
        task: The shuffle task describing the file to process.

    Returns:
        A ShuffleResult with the outcome.
    """
    source_type_dir = os.path.join(SOURCES_DIR, task.source_type)
    rel_path = os.path.relpath(task.file_path_abs, source_type_dir)

    # Load file contents for the LLM prompt (strip metadata fields)
    try:
        file_contents = load_file_without_metadata(task.file_path_abs)
    except Exception as e:
        return ShuffleResult(
            source_type=task.source_type,
            rel_original=rel_path,
            rel_new=None,
            error=f"{rel_path}: {e}",
        )

    dest_dir = pick_directory_with_llm(
        file_path=rel_path,
        file_contents=file_contents,
        source_type=task.source_type,
        source_tree=task.source_tree,
    )

    if dest_dir is None:
        return ShuffleResult(
            source_type=task.source_type,
            rel_original=rel_path,
            rel_new=None,
            error=f"{rel_path}: LLM failed to pick a valid directory after 5 attempts",
        )

    new_path = move_and_tag_file(task.file_path_abs, dest_dir, task.source_type)

    if new_path:
        rel_new = os.path.relpath(new_path, SOURCES_DIR)
        rel_original = os.path.relpath(task.file_path_abs, SOURCES_DIR)
        return ShuffleResult(
            source_type=task.source_type,
            rel_original=rel_original,
            rel_new=rel_new,
            error=None,
        )

    return ShuffleResult(
        source_type=task.source_type,
        rel_original=rel_path,
        rel_new=None,
        error=f"{rel_path}: failed to move file",
    )


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Shuffle documents to neighboring directories using LLM selection."
    )
    parser.add_argument(
        "--percentage",
        type=float,
        default=3.0,
        help="Percentage of documents to shuffle within each source type (default: 3)",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=50,
        help="Number of files to process in parallel (default: 50)",
    )
    args = parser.parse_args()

    print("Step 2: LLM-Based Shuffle")
    print("=" * 40)
    print(
        STEP_OVERVIEW.format(
            percentage=args.percentage,
            parallelism=args.parallelism,
        )
    )

    # Get top-level source types (skip files like agents.md)
    source_types = sorted(
        entry
        for entry in os.listdir(SOURCES_DIR)
        if os.path.isdir(os.path.join(SOURCES_DIR, entry))
    )

    # Build all tasks across all source types
    tasks: list[ShuffleTask] = []
    total_docs = 0

    for source_type in source_types:
        source_type_dir = os.path.join(SOURCES_DIR, source_type)
        json_files = collect_json_files(source_type_dir)

        total = len(json_files)
        total_docs += total

        if total == 0:
            print(f"[{source_type}] No JSON files found, skipping")
            continue

        # Check for nested directories
        has_subdirs = any(
            os.path.isdir(os.path.join(source_type_dir, entry))
            for entry in os.listdir(source_type_dir)
        )
        if not has_subdirs:
            print(f"[{source_type}] No nested directories, skipping")
            continue

        # Skip files already marked as noise documents
        eligible_files = [f for f in json_files if not is_noise_document(f)]
        skipped = total - len(eligible_files)
        if skipped:
            print(f"[{source_type}] Skipped {skipped} noise documents")

        if not eligible_files:
            print(f"[{source_type}] No eligible files after filtering, skipping")
            continue

        num_to_move = max(1, round(len(eligible_files) * args.percentage / 100))
        selected = random.sample(eligible_files, min(num_to_move, len(eligible_files)))
        source_tree = get_source_type_tree(source_type)

        print(
            f"[{source_type}] {total} documents, selected {len(selected)} ({args.percentage}%)"
        )

        for file_path_abs in selected:
            tasks.append(
                ShuffleTask(
                    file_path_abs=file_path_abs,
                    source_type=source_type,
                    source_tree=source_tree,
                )
            )

    if not tasks:
        print("\nNo files to shuffle.")
        return

    print(f"\nProcessing {len(tasks)} files with parallelism={args.parallelism}...")
    print()

    # Process all tasks in parallel
    moved = 0
    errors: list[str] = []
    completed = 0

    with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
        futures = {executor.submit(process_single_file, task): task for task in tasks}

        for future in as_completed(futures):
            completed += 1
            result = future.result()

            if result.error:
                errors.append(f"[{result.source_type}] {result.error}")
                print(
                    f"  [{completed}/{len(tasks)}] FAILED: [{result.source_type}] {result.rel_original}"
                )
            else:
                moved += 1
                print(
                    f"  [{completed}/{len(tasks)}] Moved: {result.rel_original} -> {result.rel_new}"
                )

    # Summary
    print("\n" + "=" * 40)
    print(f"Moved {moved} of {len(tasks)} selected ({total_docs} total documents).")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors[:20]:
            print(f"  - {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    update_statistics(
        "Stage 2: Add Noise",
        "Step 2: LLM-Based Shuffle",
        {
            "total_documents": total_docs,
            "documents_selected": len(tasks),
            "documents_moved": moved,
            "errors": len(errors),
            "shuffle_percentage": args.percentage,
        },
    )

    print("\nThis step is complete, go on to step 3 to generate miscellaneous files.")


if __name__ == "__main__":
    main()
