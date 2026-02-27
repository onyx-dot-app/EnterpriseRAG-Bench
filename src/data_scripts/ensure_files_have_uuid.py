"""Ensure all JSON files in a directory have dataset_doc_uuid."""

import argparse
import os

from src.paths import SOURCES_DIR
from src.utils.dataset_id import add_dataset_doc_uuid
from src.utils.file_io import load_json_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ensure all JSON files in a directory have dataset_doc_uuid."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=SOURCES_DIR,
        help=f"Directory to process (default: {SOURCES_DIR})",
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

    # Check which files need UUIDs
    files_without_uuid: list[str] = []
    for filepath in json_files:
        try:
            data = load_json_file(filepath)
            if "dataset_doc_uuid" not in data:
                files_without_uuid.append(filepath)
        except Exception:
            continue

    if not files_without_uuid:
        print("All files already have dataset_doc_uuid.")
        return

    print(f"Adding dataset_doc_uuid to {len(files_without_uuid)} files...")

    added = 0
    failed = 0
    for filepath in files_without_uuid:
        try:
            add_dataset_doc_uuid(filepath)
            added += 1
        except Exception as e:
            print(f"  Failed: {filepath} - {e}")
            failed += 1

    print(f"Done. Added UUIDs to {added} files, {failed} failed.")


if __name__ == "__main__":
    main()
