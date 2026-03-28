"""Remove JSON files that are invalid or empty from the sources directory.

Scans a directory for JSON files that fail to parse, are empty, or contain empty
objects/arrays, then deletes them after user confirmation.

Usage:
    python -m src.scripts.util_scripts.remove_failed_jsons [DIRECTORY] [OPTIONS]

Args:
    directory  Directory to process (default: generated_data/sources)
    --yes, -y  Skip confirmation and delete automatically
"""

import argparse
import json
import os

from src.paths import SOURCES_DIR


def is_valid_json_file(filepath: str) -> tuple[bool, str]:
    """Check if a file is a valid, non-empty JSON file.

    Returns (is_valid, reason) tuple.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for empty file
        if not content.strip():
            return False, "empty file"

        # Try to parse JSON
        data = json.loads(content)

        # Check for empty JSON object or array
        if data == {} or data == []:
            return False, "empty JSON object/array"

        return True, ""
    except json.JSONDecodeError as e:
        return False, f"invalid JSON: {e}"
    except Exception as e:
        return False, f"error reading file: {e}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove invalid or empty JSON files from a directory."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=SOURCES_DIR,
        help=f"Directory to process (default: {SOURCES_DIR})",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt and delete files automatically",
    )
    args = parser.parse_args()

    directory = args.directory

    if not os.path.exists(directory):
        print(f"Error: Directory does not exist: {directory}")
        return

    # Find all JSON files
    json_files: list[str] = []
    for root, _dirs, files in os.walk(directory):
        for filename in files:
            if filename.endswith(".json"):
                json_files.append(os.path.join(root, filename))

    if not json_files:
        print(f"No JSON files found in {directory}")
        return

    print(f"Found {len(json_files)} JSON files in {directory}")
    print("Checking for invalid or empty files...")
    print()

    # Check which files are invalid
    invalid_files: list[tuple[str, str]] = []  # (path, reason)
    for filepath in json_files:
        is_valid, reason = is_valid_json_file(filepath)
        if not is_valid:
            invalid_files.append((filepath, reason))

    if not invalid_files:
        print("All files are valid JSON files.")
        return

    # Print invalid files
    print(f"Found {len(invalid_files)} invalid file(s):")
    print()
    for filepath, reason in invalid_files:
        relative_path = os.path.relpath(filepath, directory)
        print(f"  - {relative_path}: {reason}")
    print()

    # Prompt for confirmation
    if not args.yes:
        response = (
            input(f"Delete these {len(invalid_files)} file(s)? [y/N]: ").strip().lower()
        )
        if response not in ("y", "yes"):
            print("Aborted. No files deleted.")
            return

    # Delete files
    deleted = 0
    failed = 0
    for filepath, _ in invalid_files:
        try:
            os.remove(filepath)
            deleted += 1
        except Exception as e:
            print(f"  Failed to delete {filepath}: {e}")
            failed += 1

    print(f"Done. Deleted {deleted} file(s), {failed} failed.")


if __name__ == "__main__":
    main()
