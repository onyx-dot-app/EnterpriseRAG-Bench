"""Ensure all JSON files in a directory have field labels (title_field_name, content_field_names)."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.paths import SOURCES_DIR
from src.utils.field_labeling import get_documents_without_labels, label_single_document


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ensure all JSON files in a directory have field labels."
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

    # Find all JSON files without labels
    files_to_process = get_documents_without_labels(directory)

    if not files_to_process:
        print(f"All JSON files in {directory} already have field labels.")
        return

    print(f"Found {len(files_to_process)} files without field labels in {directory}")
    print(f"Using parallelism: {max_parallelism}")
    print()

    # Process in parallel
    succeeded = 0
    failed: list[tuple[str, str]] = []

    # Use quiet mode when running in parallel
    use_quiet = max_parallelism > 1

    with ThreadPoolExecutor(max_workers=max_parallelism) as executor:
        futures = {
            executor.submit(label_single_document, filepath, use_quiet): filepath
            for filepath in files_to_process
        }

        with tqdm(total=len(files_to_process), desc="Labeling documents") as pbar:
            for future in as_completed(futures):
                filepath = futures[future]
                try:
                    success, message = future.result()
                    if success:
                        succeeded += 1
                    else:
                        failed.append((filepath, message))
                        tqdm.write(f"[FAIL] {filepath}: {message}")
                except Exception as e:
                    failed.append((filepath, str(e)))
                    tqdm.write(f"[FAIL] {filepath}: {e}")
                pbar.update(1)

    print()
    print(f"Done. Labeled {succeeded} files, {len(failed)} failed.")

    if failed:
        print()
        print(f"Failed files ({len(failed)}):")
        for filepath, error in failed[:20]:
            print(f"  - {filepath}: {error}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more errors")


if __name__ == "__main__":
    main()
