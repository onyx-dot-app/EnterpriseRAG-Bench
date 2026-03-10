"""Clean up volume documents and track non-volume document UUIDs.

Tracks UUIDs from:
- projects: from question_cache/project_*.json
- completeness: from question_cache/completeness_*.json
- duplication: from question_cache/duplication_*.json

Also flags project files that don't have UUIDs and optionally cleans up:
1. Orphaned source files that don't correspond to any tracked UUIDs
2. Files mentioned in volume/*.json (and clears those references)
"""

from pathlib import Path

from src.paths import DEBUG_DIR, QUESTION_CACHE_DIR, SOURCES_DIR, VOLUME_DIR
from src.utils import confirm_yes_no, load_json_file, write_json_file


NON_VOLUME_DOCUMENTS_PATH = f"{DEBUG_DIR}/non_volume_documents.json"


def get_project_uuids(question_cache_dir: Path) -> list[str]:
    """Extract all document UUIDs from project question cache files."""
    uuids: set[str] = set()

    for project_file in sorted(question_cache_dir.glob("project_*.json")):
        data = load_json_file(str(project_file))
        documents = data.get("documents", [])
        uuids.update(documents)

    return sorted(uuids)


def get_completeness_uuids(question_cache_dir: Path) -> list[str]:
    """Extract all document UUIDs from completeness question cache files."""
    uuids: set[str] = set()

    for completeness_file in sorted(question_cache_dir.glob("completeness_*.json")):
        data = load_json_file(str(completeness_file))
        documents = data.get("documents", [])
        uuids.update(documents)

    return sorted(uuids)


def get_duplication_uuids(question_cache_dir: Path) -> list[str]:
    """Extract all document UUIDs from duplication question cache files."""
    uuids: set[str] = set()

    for duplication_file in sorted(question_cache_dir.glob("duplication_*.json")):
        data = load_json_file(str(duplication_file))

        if "document_old" in data:
            uuids.add(data["document_old"])
        if "document_new" in data:
            uuids.add(data["document_new"])

    return sorted(uuids)


def collect_files_from_topic(topic_data: dict) -> list[str]:
    """Recursively collect all file paths from a topic and its sub_topics."""
    files: list[str] = []

    # Get files at this level
    files.extend(topic_data.get("files", []))

    # Recursively get files from sub_topics
    sub_topics = topic_data.get("sub_topics", {})
    for sub_topic_data in sub_topics.values():
        files.extend(collect_files_from_topic(sub_topic_data))

    return files


def get_volume_file_paths(volume_dir: Path) -> set[str]:
    """Extract all file paths from volume JSON files (including sub_topics)."""
    file_paths: set[str] = set()

    for volume_file in sorted(volume_dir.glob("*.json")):
        try:
            data = load_json_file(str(volume_file))
            topics = data.get("topics", {})

            for topic_data in topics.values():
                files = collect_files_from_topic(topic_data)
                file_paths.update(files)
        except Exception as e:
            print(f"  Warning: Could not read {volume_file.name}: {e}")

    return file_paths


def clear_files_from_topic(topic_data: dict) -> int:
    """Recursively clear all file lists from a topic and its sub_topics."""
    cleared = 0

    # Clear files at this level
    if "files" in topic_data:
        cleared += len(topic_data["files"])
        topic_data["files"] = []

    # Recursively clear files from sub_topics
    sub_topics = topic_data.get("sub_topics", {})
    for sub_topic_data in sub_topics.values():
        cleared += clear_files_from_topic(sub_topic_data)

    return cleared


def clear_volume_file_references(volume_dir: Path) -> int:
    """Clear all file references from volume JSON files. Returns count of cleared refs."""
    total_cleared = 0

    for volume_file in sorted(volume_dir.glob("*.json")):
        try:
            data = load_json_file(str(volume_file))
            topics = data.get("topics", {})
            file_cleared = 0

            for topic_data in topics.values():
                file_cleared += clear_files_from_topic(topic_data)

            if file_cleared > 0:
                write_json_file(str(volume_file), data)
                print(f"    {volume_file.name}: cleared {file_cleared} references")

            total_cleared += file_cleared
        except Exception as e:
            print(f"  Warning: Could not update {volume_file.name}: {e}")

    return total_cleared




def find_orphaned_source_files(
    sources_dir: Path,
    all_tracked_uuids: set[str],
) -> list[Path]:
    """Find source files not matching any tracked UUID."""
    orphaned_files: list[Path] = []

    for source_file in sorted(sources_dir.rglob("*.json")):
        # Skip agents.md files and other non-document files
        if source_file.name == "agents.md":
            continue

        try:
            data = load_json_file(str(source_file))
            file_uuid = data.get("dataset_doc_uuid")

            if file_uuid is None or file_uuid not in all_tracked_uuids:
                orphaned_files.append(source_file)
        except Exception:
            # If we can't read the file, consider it orphaned
            orphaned_files.append(source_file)

    return orphaned_files


def cleanup_files(files_to_delete: list[Path]) -> int:
    """Delete files and return count of deleted files."""
    deleted_count = 0

    for file_path in files_to_delete:
        try:
            if file_path.exists():
                file_path.unlink()
                deleted_count += 1
        except Exception as e:
            print(f"  Failed to delete {file_path}: {e}")

    return deleted_count


def main() -> None:
    """Main function to generate the non-volume documents tracker and cleanup."""
    base_dir = Path.cwd()
    question_cache_dir = base_dir / QUESTION_CACHE_DIR
    sources_dir = base_dir / SOURCES_DIR
    volume_dir = base_dir / VOLUME_DIR
    output_dir = base_dir / DEBUG_DIR
    output_file = base_dir / NON_VOLUME_DOCUMENTS_PATH

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect UUIDs from each source
    print("Collecting document UUIDs from question cache...")
    project_uuids = get_project_uuids(question_cache_dir)
    completeness_uuids = get_completeness_uuids(question_cache_dir)
    duplication_uuids = get_duplication_uuids(question_cache_dir)

    # Build output structure
    output_data = {
        "projects": project_uuids,
        "completeness": completeness_uuids,
        "duplication": duplication_uuids,
    }

    # Write output file
    write_json_file(str(output_file), output_data)

    # Print summary
    print(f"\nNon-volume document tracker written to: {output_file}")
    print(f"  - projects: {len(project_uuids)} UUIDs")
    print(f"  - completeness: {len(completeness_uuids)} UUIDs")
    print(f"  - duplication: {len(duplication_uuids)} UUIDs")

    # Cleanup option
    print("\n" + "=" * 60)
    if confirm_yes_no("Would you like to run cleanup?"):
        all_tracked_uuids = set(project_uuids) | set(completeness_uuids) | set(duplication_uuids)

        # Find orphaned files
        print(f"\nScanning {sources_dir} for orphaned files...")
        orphaned_files = find_orphaned_source_files(sources_dir, all_tracked_uuids)

        # Get volume file paths (including from sub_topics)
        print(f"Collecting file paths from volume JSONs in {volume_dir}...")
        volume_file_paths = get_volume_file_paths(volume_dir)

        # Convert volume paths to Path objects
        volume_files_to_delete = [base_dir / p for p in volume_file_paths]

        # Combine: orphaned files + volume-referenced files (deduplicated)
        all_orphaned_set = set(orphaned_files)
        all_volume_set = set(volume_files_to_delete)

        # Files only in orphaned (not in volume)
        orphan_only = all_orphaned_set - all_volume_set
        # Files only in volume (not already orphaned)
        volume_only = all_volume_set - all_orphaned_set
        # Files in both
        in_both = all_orphaned_set & all_volume_set

        total_to_delete = len(orphan_only) + len(volume_only) + len(in_both)

        print(f"\nCleanup summary:")
        print(f"  - Orphaned files (not in volume): {len(orphan_only)}")
        print(f"  - Volume-referenced files: {len(volume_only) + len(in_both)}")
        print(f"  - Total files to delete: {total_to_delete}")
        print(f"  - Volume JSON references to clear: {len(volume_file_paths)}")

        if total_to_delete == 0 and len(volume_file_paths) == 0:
            print("\nNothing to clean up.")
        else:
            # Show some examples
            all_files_to_delete = list(orphan_only | volume_only | in_both)
            if all_files_to_delete:
                print(f"\nExample files to delete:")
                for file_path in all_files_to_delete[:10]:
                    if file_path.exists():
                        try:
                            print(f"  - {file_path.relative_to(base_dir)}")
                        except ValueError:
                            print(f"  - {file_path}")
                if len(all_files_to_delete) > 10:
                    print(f"  ... and {len(all_files_to_delete) - 10} more")

            print()
            if confirm_yes_no(
                f"Are you sure you want to DELETE {total_to_delete} files and clear volume references?"
            ):
                # Step 1: Delete files
                print("\nStep 1: Deleting files...")
                deleted_count = cleanup_files(all_files_to_delete)
                print(f"  Deleted {deleted_count} files.")

                # Step 2: Clear volume JSON references
                print("\nStep 2: Clearing volume JSON references (topics and sub_topics)...")
                cleared_refs = clear_volume_file_references(volume_dir)
                print(f"  Total cleared: {cleared_refs} file references.")

                print("\nCleanup complete.")
            else:
                print("Cleanup cancelled.")
    else:
        print("Skipping cleanup.")


if __name__ == "__main__":
    main()
