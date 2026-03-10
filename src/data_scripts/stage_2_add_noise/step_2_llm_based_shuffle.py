"""Script to shuffle documents using LLM-chosen neighboring directories.

Unlike step 1 (pure random), this uses an LLM to pick a plausible but
non-ideal directory for each selected document within the same source type.
"""

import argparse
import os
import random

from src.llm import Message, get_llm
from src.paths import SOURCES_DIR, SOURCE_TREE_PATH
from src.prompts.neighboring_shuffle import PATH_ERROR_RESPONSE, SHUFFLE_PROMPT
from src.utils.directory_tree import get_directory_tree
from src.utils.file_io import load_file, load_json_file, write_json_file


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
    """Extract the directory tree for a single source type from the full tree.

    Falls back to generating it directly if the cached tree isn't available.

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

    Args:
        proposed_dir: The LLM's proposed directory path.
        source_type: Name of the source type.

    Returns:
        Absolute path to the directory if valid, None otherwise.
    """
    cleaned = proposed_dir.strip("`\"' \n")

    # Strip leading sources/ or source_type/ prefixes the LLM might include
    prefixes = [
        f"sources/{source_type}/",
        f"sources/{source_type}",
        f"{source_type}/",
        f"{source_type}",
    ]
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # Remove leading/trailing slashes
    cleaned = cleaned.strip("/")

    source_type_dir = os.path.join(SOURCES_DIR, source_type)

    if cleaned:
        abs_dir = os.path.join(source_type_dir, cleaned)
    else:
        # LLM returned just the source type root
        abs_dir = source_type_dir

    if os.path.isdir(abs_dir):
        return abs_dir
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
    prompt = SHUFFLE_PROMPT.format(
        file_path=file_path,
        file_contents=file_contents,
        source_directory_structure=source_tree,
    )

    llm = get_llm(tools=None, quiet=False)
    messages: list[Message] = [Message(role="user", content=prompt)]

    for attempt in range(max_attempts):
        if attempt > 0:
            print(f"    Attempt {attempt + 1}/{max_attempts}...")

        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
                response += chunk
        print()

        abs_dir = validate_proposed_dir(response.strip(), source_type)
        if abs_dir is not None:
            # Make sure it's different from the file's current directory
            current_dir = os.path.dirname(
                os.path.join(SOURCES_DIR, source_type, file_path)
            )
            if abs_dir != current_dir:
                return abs_dir
            print("    LLM chose the same directory as the original, retrying...")

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
# Per-Source Shuffle
# =============================================================================


def shuffle_source_type(
    source_type: str,
    percentage: float,
) -> tuple[int, int]:
    """Shuffle a percentage of documents within a source type using the LLM.

    Args:
        source_type: Name of the source type directory.
        percentage: Percentage of files to shuffle (0-100).

    Returns:
        (moved_count, total_count) tuple.
    """
    source_type_dir = os.path.join(SOURCES_DIR, source_type)
    json_files = collect_json_files(source_type_dir)

    total = len(json_files)
    if total == 0:
        print(f"  No JSON files found in {source_type}")
        return 0, 0

    num_to_move = max(1, round(total * percentage / 100))
    selected = random.sample(json_files, min(num_to_move, total))

    print(f"  {total} documents, shuffling {len(selected)} ({percentage}%)")

    source_tree = get_source_type_tree(source_type)

    moved = 0
    errors: list[str] = []

    for i, file_path_abs in enumerate(selected, 1):
        rel_path = os.path.relpath(file_path_abs, source_type_dir)
        print(f"\n  [{i}/{len(selected)}] {rel_path}")

        # Load file contents for the LLM prompt
        try:
            file_contents = load_file(file_path_abs)
        except Exception as e:
            print(f"    Error reading file: {e}")
            errors.append(f"{rel_path}: {e}")
            continue

        dest_dir = pick_directory_with_llm(
            file_path=rel_path,
            file_contents=file_contents,
            source_type=source_type,
            source_tree=source_tree,
        )

        if dest_dir is None:
            msg = f"{rel_path}: LLM failed to pick a valid directory after 5 attempts"
            print(f"    ERROR: {msg}")
            errors.append(msg)
            continue

        new_path = move_and_tag_file(file_path_abs, dest_dir, source_type)

        if new_path:
            rel_new = os.path.relpath(new_path, SOURCES_DIR)
            rel_original = os.path.relpath(file_path_abs, SOURCES_DIR)
            print(f"    Moved: {rel_original} -> {rel_new}")
            moved += 1
        else:
            errors.append(f"{rel_path}: failed to move file")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for err in errors[:10]:
            print(f"    - {err}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")

    return moved, total


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
        default=5.0,
        help="Percentage of documents to shuffle within each source type (default: 5)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    print("Step 2: LLM-Based Shuffle")
    print("=" * 40)
    print(f"Shuffling {args.percentage}% of documents per source type using LLM.")
    print()

    if args.seed is not None:
        random.seed(args.seed)
        print(f"Random seed: {args.seed}")
        print()

    # Get top-level source types (skip files like agents.md)
    source_types = sorted(
        entry
        for entry in os.listdir(SOURCES_DIR)
        if os.path.isdir(os.path.join(SOURCES_DIR, entry))
    )

    total_moved = 0
    total_docs = 0

    for source_type in source_types:
        print(f"\n[{source_type}]")
        moved, count = shuffle_source_type(source_type, args.percentage)
        total_moved += moved
        total_docs += count

    print("\n" + "=" * 40)
    print(f"Done. Moved {total_moved} of {total_docs} total documents.")


if __name__ == "__main__":
    main()
