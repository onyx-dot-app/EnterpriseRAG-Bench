"""Script to randomly shuffle a percentage of documents within each source type.

Moves files to random directories within the same source type and records
the original location in the document JSON. Documents are chosen using a random walk
over the directory tree so selection reflects structure rather than file count per folder.
No cross-source shuffling occurs to keep documents compliant with their source format.

Usage:
    python -m src.scripts.data_gen_stage_2_add_noise.step_1_random_shuffle [OPTIONS]

Args:
    --percentage  Percentage of documents to shuffle within each source type (default: 5.0)
"""

import argparse
import os
import random

from src.paths import SOURCES_DIR
from src.utils.file_io import load_json_file, write_json_file
from src.utils.statistics import update_statistics

STEP_OVERVIEW = """\
Randomly shuffles a percentage of documents within each source type.
Documents are chosen via a random walk over the directory tree so selection
reflects structure, not file count. No cross-source shuffling to keep
documents compliant with their source format.

Shuffling {{percentage}}% of documents within each source type.
"""


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


def collect_directories(source_type_dir: str) -> list[str]:
    """Collect all directories under a source type directory.

    Excludes the source type root itself (only subdirectories that contain
    or could contain files).

    Args:
        source_type_dir: Absolute path to a source type directory.

    Returns:
        List of absolute paths to directories.
    """
    directories: list[str] = []
    for root, dirs, _files in os.walk(source_type_dir):
        for d in dirs:
            directories.append(os.path.join(root, d))
    return directories


def pick_destination_dir(
    current_dir: str,
    all_dirs: list[str],
    max_attempts: int = 50,
) -> str | None:
    """Pick a random destination directory different from the current one.

    Args:
        current_dir: Absolute path to the file's current directory.
        all_dirs: List of all candidate directories.
        max_attempts: Maximum random picks before giving up.

    Returns:
        Absolute path to the chosen directory, or None if no different
        directory could be found.
    """
    if len(all_dirs) <= 1:
        return None

    for _ in range(max_attempts):
        candidate = random.choice(all_dirs)
        if candidate != current_dir:
            return candidate
    return None


def move_and_tag_file(
    file_path: str,
    dest_dir: str,
    source_type: str,
) -> str | None:
    """Move a JSON file to a new directory and add original_location field.

    Args:
        file_path: Absolute path to the JSON file.
        dest_dir: Absolute path to the destination directory.
        source_type: Name of the source type (e.g. "confluence").

    Returns:
        The new absolute path on success, or None on failure.
    """
    source_type_dir = os.path.join(SOURCES_DIR, source_type)
    # Build original_location: source_type/relative/path/file.json
    rel_from_source_type = os.path.relpath(file_path, source_type_dir)
    original_location = f"{source_type}/{rel_from_source_type}"

    # Load and update the document
    try:
        data = load_json_file(file_path)
    except Exception as e:
        print(f"  Error loading {file_path}: {e}")
        return None

    data["original_location"] = original_location

    # Determine new path
    filename = os.path.basename(file_path)
    new_path = os.path.join(dest_dir, filename)

    # Handle filename collision
    if os.path.exists(new_path):
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(new_path):
            new_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
            counter += 1

    # Write to new location, then remove original
    try:
        write_json_file(new_path, data)
        os.remove(file_path)
    except Exception as e:
        print(f"  Error moving {file_path}: {e}")
        return None

    return new_path


def shuffle_source_type(
    source_type: str,
    percentage: float,
) -> tuple[int, int]:
    """Shuffle a percentage of documents within a single source type.

    Args:
        source_type: Name of the source type directory.
        percentage: Percentage of files to shuffle (0-100).

    Returns:
        (moved_count, total_count) tuple.
    """
    source_type_dir = os.path.join(SOURCES_DIR, source_type)
    json_files = collect_json_files(source_type_dir)
    directories = collect_directories(source_type_dir)

    total = len(json_files)
    if total == 0:
        print(f"  No JSON files found in {source_type}")
        return 0, 0

    if not directories:
        print(f"  No subdirectories found in {source_type}, skipping")
        return 0, total

    num_to_move = max(1, round(total * percentage / 100))
    selected = random.sample(json_files, min(num_to_move, total))

    print(f"  {total} documents, moving {len(selected)} ({percentage}%)")

    moved = 0
    for file_path in selected:
        current_dir = os.path.dirname(file_path)
        dest_dir = pick_destination_dir(current_dir, directories)

        if dest_dir is None:
            print(f"  Skipping {os.path.basename(file_path)}: no alternate directory")
            continue

        rel_original = os.path.relpath(file_path, SOURCES_DIR)
        new_path = move_and_tag_file(file_path, dest_dir, source_type)

        if new_path:
            rel_new = os.path.relpath(new_path, SOURCES_DIR)
            print(f"  Moved: {rel_original} -> {rel_new}")
            moved += 1

    return moved, total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Randomly shuffle documents within each source type to add noise."
    )
    parser.add_argument(
        "--percentage",
        type=float,
        default=5.0,
        help="Percentage of documents to shuffle within each source type (default: 5)",
    )
    args = parser.parse_args()

    print("Step 1: Random Shuffle")
    print("=" * 40)
    print(STEP_OVERVIEW.format(percentage=args.percentage))

    # Get top-level source types (skip files like agents.md)
    source_types = sorted(
        entry
        for entry in os.listdir(SOURCES_DIR)
        if os.path.isdir(os.path.join(SOURCES_DIR, entry))
    )

    total_moved = 0
    total_docs = 0

    for source_type in source_types:
        print(f"[{source_type}]")
        moved, count = shuffle_source_type(source_type, args.percentage)
        total_moved += moved
        total_docs += count
        print()

    print("=" * 40)
    print(f"Moved {total_moved} of {total_docs} total documents.")

    update_statistics(
        "Stage 2: Add Noise",
        "Step 1: Random Shuffle",
        {
            "total_documents": total_docs,
            "documents_moved": total_moved,
            "shuffle_percentage": args.percentage,
        },
    )

    print("\nThis step is complete, go on to step 2 to perform LLM-based shuffling.")


if __name__ == "__main__":
    main()
