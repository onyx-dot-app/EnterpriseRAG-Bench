"""Ensure all JSON files in a directory have field labels and correct field ordering.

Scans a directory for JSON files missing title_field_name or content_field_names, uses
an LLM to assign labels, and fixes trailing field ordering. Runs labeling in parallel.

Usage:
    python -m src.scripts.util_scripts.ensure_files_have_labels [DIRECTORY] [OPTIONS]

Args:
    directory      Directory to process (default: generated_data/sources)
    --parallelism  Number of parallel labeling operations (default: 20)
"""

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.paths import SOURCES_DIR
from src.utils.field_labeling import label_single_document
from src.utils.field_ordering import needs_reordering, reorder_document_fields
from src.utils.file_io import load_json_file, write_json_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ensure all JSON files in a directory have field labels and correct field ordering."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=SOURCES_DIR,
        help=f"Directory to process (default: {SOURCES_DIR})",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=20,
        help="Number of parallel labeling operations (default: 20)",
    )
    args = parser.parse_args()

    directory = args.directory
    max_parallelism = args.parallelism

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

    # Check which files need labels or reordering
    files_to_process: list[tuple[str, bool, bool]] = (
        []
    )  # (path, needs_labels, needs_reorder)
    for filepath in json_files:
        try:
            data = load_json_file(filepath)
            needs_labels = (
                "title_field_name" not in data or "content_field_names" not in data
            )
            needs_reorder = needs_reordering(data)
            if needs_labels or needs_reorder:
                files_to_process.append((filepath, needs_labels, needs_reorder))
        except Exception:
            continue

    if not files_to_process:
        print("All files already have field labels and correct ordering.")
        return

    needs_labels_count = sum(
        1 for _, needs_labels, _ in files_to_process if needs_labels
    )
    needs_reorder_count = sum(
        1 for _, _, needs_reorder in files_to_process if needs_reorder
    )
    print(
        f"Processing {len(files_to_process)} files ({needs_labels_count} need labels, {needs_reorder_count} need reordering)..."
    )
    print(f"Using parallelism: {max_parallelism}")
    print()

    # Use quiet mode when running in parallel
    use_quiet = max_parallelism > 1

    labeled = 0
    reordered = 0
    failed: list[tuple[str, str]] = []

    def process_file(
        filepath: str, file_needs_labels: bool, file_needs_reorder: bool
    ) -> tuple[bool, str, bool, bool]:
        """Process a single file. Returns (success, message, did_label, did_reorder)."""
        try:
            if file_needs_labels:
                # label_single_document will also fix ordering
                success, message = label_single_document(
                    filepath, quiet=use_quiet, fix_ordering=True
                )
                if success:
                    return (True, message, True, file_needs_reorder)
                else:
                    return (False, message, False, False)
            elif file_needs_reorder:
                # Only fix ordering
                data = load_json_file(filepath)
                data = reorder_document_fields(data)
                write_json_file(filepath, data)
                return (True, "Fixed ordering", False, True)
            return (True, "No changes needed", False, False)
        except Exception as e:
            return (False, str(e), False, False)

    with ThreadPoolExecutor(max_workers=max_parallelism) as executor:
        futures = {
            executor.submit(
                process_file, filepath, needs_labels, needs_reorder
            ): filepath
            for filepath, needs_labels, needs_reorder in files_to_process
        }

        with tqdm(total=len(files_to_process), desc="Processing documents") as pbar:
            for future in as_completed(futures):
                filepath = futures[future]
                try:
                    success, message, did_label, did_reorder = future.result()
                    if success:
                        if did_label:
                            labeled += 1
                        if did_reorder:
                            reordered += 1
                    else:
                        failed.append((filepath, message))
                        tqdm.write(f"[FAIL] {filepath}: {message}")
                except Exception as e:
                    failed.append((filepath, str(e)))
                    tqdm.write(f"[FAIL] {filepath}: {e}")
                pbar.update(1)

    print()
    print(
        f"Done. Labeled {labeled} files, fixed ordering in {reordered} files, {len(failed)} failed."
    )

    if failed:
        print()
        print(f"Failed files ({len(failed)}):")
        for filepath, error in failed[:20]:
            print(f"  - {filepath}: {error}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more errors")


if __name__ == "__main__":
    main()
