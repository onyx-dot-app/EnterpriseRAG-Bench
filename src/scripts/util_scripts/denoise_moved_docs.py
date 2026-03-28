"""Revert shuffled documents back to their original locations.

Finds all JSON documents with an 'original_location' field (set during Stage 2 shuffle
steps), moves them back to their original paths, and removes the field. Useful for
undoing noise injection during debugging or dataset regeneration.

Usage:
    python -m src.scripts.util_scripts.denoise_moved_docs

No arguments.
"""

import os

from src.paths import SOURCES_DIR
from src.utils.file_io import load_json_file, write_json_file


def find_moved_documents() -> list[str]:
    """Find all JSON files that have an original_location field.

    Returns:
        List of absolute paths to moved documents.
    """
    moved: list[str] = []
    for root, _dirs, files in os.walk(SOURCES_DIR):
        for filename in files:
            if not filename.endswith(".json"):
                continue
            file_path = os.path.join(root, filename)
            try:
                data = load_json_file(file_path)
                if "original_location" in data:
                    moved.append(file_path)
            except Exception:
                continue
    return moved


def restore_document(file_path: str) -> tuple[bool, str]:
    """Move a document back to its original location and remove the field.

    Args:
        file_path: Absolute path to the moved document.

    Returns:
        (success, message) tuple.
    """
    try:
        data = load_json_file(file_path)
    except Exception as e:
        return False, f"Error loading {file_path}: {e}"

    original_location = data.get("original_location")
    if not original_location:
        return False, f"No original_location in {file_path}"

    original_abs = os.path.join(SOURCES_DIR, original_location)
    original_dir = os.path.dirname(original_abs)

    if not os.path.isdir(original_dir):
        return False, f"Original directory no longer exists: {original_dir}"

    # Remove the original_location field
    del data["original_location"]

    # Handle collision at original location
    dest_path = original_abs
    if os.path.exists(dest_path) and os.path.abspath(dest_path) != os.path.abspath(
        file_path
    ):
        base, ext = os.path.splitext(os.path.basename(dest_path))
        counter = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(original_dir, f"{base}_{counter}{ext}")
            counter += 1

    try:
        write_json_file(dest_path, data)
        # Only remove the source if it's a different file
        if os.path.abspath(file_path) != os.path.abspath(dest_path):
            os.remove(file_path)
    except Exception as e:
        return False, f"Error restoring {file_path}: {e}"

    rel_current = os.path.relpath(file_path, SOURCES_DIR)
    rel_dest = os.path.relpath(dest_path, SOURCES_DIR)
    return True, f"{rel_current} -> {rel_dest}"


def main() -> None:
    print("Denoise: Restore Moved Documents")
    print("=" * 40)
    print()

    moved_files = find_moved_documents()

    if not moved_files:
        print("No documents with original_location found.")
        return

    print(f"Found {len(moved_files)} moved document(s). Restoring...")
    print()

    restored = 0
    errors: list[str] = []

    for file_path in moved_files:
        success, message = restore_document(file_path)
        if success:
            restored += 1
            print(f"  Restored: {message}")
        else:
            errors.append(message)
            print(f"  FAILED: {message}")

    print()
    print("=" * 40)
    print(f"Restored {restored} of {len(moved_files)} documents.")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors[:20]:
            print(f"  - {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")


if __name__ == "__main__":
    main()
