"""Ensure all JSON files in a directory have dataset_doc_uuid and correct field ordering.

Scans a directory for JSON files missing a dataset_doc_uuid, adds one, and fixes
trailing field ordering where needed.

Usage:
    python -m src.scripts.util_scripts.ensure_files_have_uuid [DIRECTORY]

Args:
    directory  Directory to process (default: generated_data/sources)
"""

import argparse
import os

from src.paths import SOURCES_DIR
from src.utils.dataset_id import add_dataset_doc_uuid
from src.utils.field_ordering import needs_reordering, reorder_document_fields
from src.utils.file_io import load_json_file, write_json_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ensure all JSON files in a directory have dataset_doc_uuid and correct field ordering."
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

    # Check which files need UUIDs or reordering
    files_to_process: list[tuple[str, bool, bool]] = (
        []
    )  # (path, needs_uuid, needs_reorder)
    for filepath in json_files:
        try:
            data = load_json_file(filepath)
            needs_uuid = "dataset_doc_uuid" not in data
            needs_reorder = needs_reordering(data)
            if needs_uuid or needs_reorder:
                files_to_process.append((filepath, needs_uuid, needs_reorder))
        except Exception:
            continue

    if not files_to_process:
        print("All files already have dataset_doc_uuid and correct ordering.")
        return

    needs_uuid_count = sum(1 for _, needs_uuid, _ in files_to_process if needs_uuid)
    needs_reorder_count = sum(
        1 for _, _, needs_reorder in files_to_process if needs_reorder
    )
    print(
        f"Processing {len(files_to_process)} files ({needs_uuid_count} need UUID, {needs_reorder_count} need reordering)..."
    )

    added = 0
    reordered = 0
    failed = 0

    for filepath, file_needs_uuid, file_needs_reorder in files_to_process:
        try:
            if file_needs_uuid:
                # add_dataset_doc_uuid will also fix ordering
                add_dataset_doc_uuid(filepath, fix_ordering=True)
                added += 1
                if file_needs_reorder:
                    reordered += 1
            elif file_needs_reorder:
                # Only fix ordering
                data = load_json_file(filepath)
                data = reorder_document_fields(data)
                write_json_file(filepath, data)
                reordered += 1
        except Exception as e:
            print(f"  Failed: {filepath} - {e}")
            failed += 1

    print(
        f"Done. Added UUIDs to {added} files, fixed ordering in {reordered} files, {failed} failed."
    )


if __name__ == "__main__":
    main()
