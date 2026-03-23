"""Export generated data to plain text or JSON files with optional zip packaging."""

import argparse
import json
import os
import random
import shutil
import zipfile

from pydantic import BaseModel

from src.paths import EXPORT_DATA_DIR, QUESTIONS_PATH, SOURCES_DIR
from src.utils import (
    confirm_yes_no,
    DocumentFieldError,
    extract_document_content,
    load_json_file,
)


# Environment variable to enable Onyx metadata format
ONYX_FORMAT_ENV_VAR = "EXPORT_IN_ONYX_FORMAT"


class ExportConfig(BaseModel):
    """Configuration for the export process."""

    sources: list[str] | None = None
    create_zip: bool = False
    max_files_per_zip: int | None = None
    max_files: int | None = None
    random_sample: bool = False
    flatten: bool = False
    export_format: str = "txt"
    split_by_source: bool = False
    onyx_format: bool = False


class ExportStats(BaseModel):
    """Statistics from the export process."""

    total_files: int = 0
    exported_files: int = 0
    skipped_missing_fields: int = 0
    errors: list[str] = []


class FileMetadata(BaseModel):
    """Metadata for a single exported file (for Onyx format)."""

    filename: str  # Just the filename (for .onyx_metadata.json output)
    id: str
    title: str
    full_path: str = ""  # Internal: full relative path for zip filtering


def directory_exists(path: str) -> bool:
    """Check if a directory exists."""
    return os.path.exists(path) and os.path.isdir(path)


def validate_document(data: dict) -> tuple[bool, str | None]:
    """
    Validate that a document has the required fields for export.

    Uses extract_document_content for field validation and additionally
    checks for dataset_doc_uuid.

    Args:
        data: The document data.

    Returns:
        (is_valid, error_message) tuple.
    """
    # Check for dataset_doc_uuid (not checked by extract_document_content)
    if "dataset_doc_uuid" not in data:
        return False, "Missing required field: dataset_doc_uuid"

    # Use shared utility for field validation
    try:
        extract_document_content(data)
    except DocumentFieldError as e:
        return False, str(e)

    return True, None


def convert_to_text(data: dict, include_title: bool = True) -> str:
    """
    Convert a document to plain text format.

    Format (with title):
    - First line: title
    - Two newlines
    - Content fields separated by newlines (without field name headers)

    Format (without title, for Onyx format):
    - Content fields separated by newlines (title is in metadata file)

    Args:
        data: The document data.
        include_title: Whether to include title in the text output.

    Returns:
        The plain text content.
    """
    # Get title using shared utility
    title, _ = extract_document_content(data)

    # Build content without field headers (different from extract_document_content)
    content_fields = data["content_field_names"]
    contents = []

    for field in content_fields:
        content = data[field]
        if isinstance(content, list):
            contents.append("\n".join(str(item) for item in content))
        else:
            contents.append(str(content))

    if include_title:
        return f"{title}\n\n{chr(10).join(contents)}"
    else:
        return chr(10).join(contents)


def get_export_filename(uuid: str, original_filename: str) -> str:
    """
    Generate the export filename with UUID prefix.

    Args:
        uuid: The dataset_doc_uuid.
        original_filename: The original JSON filename.

    Returns:
        The new filename in format: {uuid}__{original_name}.txt
    """
    base_name = os.path.splitext(original_filename)[0]
    return f"{uuid}__{base_name}.txt"


def collect_source_files(config: ExportConfig) -> list[str]:
    """
    Collect all JSON file paths from the source directories.

    Args:
        config: Export configuration (uses sources filter).

    Returns:
        List of absolute file paths to JSON files.
    """
    source_dirs = os.listdir(SOURCES_DIR)
    if config.sources:
        source_dirs = [s for s in source_dirs if s in config.sources]

    all_files: list[str] = []
    for source in sorted(source_dirs):
        source_path = os.path.join(SOURCES_DIR, source)
        if not os.path.isdir(source_path):
            continue
        for root, _dirs, files in os.walk(source_path):
            for filename in files:
                if filename.endswith(".json"):
                    all_files.append(os.path.join(root, filename))

    if config.random_sample:
        random.shuffle(all_files)

    if config.max_files is not None:
        all_files = all_files[: config.max_files]

    return all_files


def export_single_file(
    file_path: str,
    config: ExportConfig,
) -> tuple[str | None, FileMetadata | None, str | None]:
    """
    Export a single JSON file to the configured format.

    Args:
        file_path: Absolute path to the source JSON file.
        config: Export configuration.

    Returns:
        Tuple of (exported_path, file_metadata_or_none, error_or_none).
    """
    try:
        data = load_json_file(file_path)

        is_valid, error = validate_document(data)
        if not is_valid:
            return None, None, f"{file_path}: {error}"

        title, _ = extract_document_content(data)
        uuid = data["dataset_doc_uuid"]
        filename = os.path.basename(file_path)
        rel_path = os.path.relpath(os.path.dirname(file_path), SOURCES_DIR)

        if config.export_format == "json":
            export_filename = filename
        else:
            export_filename = get_export_filename(uuid, filename)

        if config.flatten:
            export_subdir = EXPORT_DATA_DIR
        else:
            export_subdir = os.path.join(EXPORT_DATA_DIR, rel_path)

        os.makedirs(export_subdir, exist_ok=True)
        export_path = os.path.join(export_subdir, export_filename)

        if config.export_format == "json":
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            text_content = convert_to_text(data, include_title=not config.onyx_format)
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(text_content)

        metadata = None
        if config.onyx_format:
            full_rel_path = os.path.join(rel_path, export_filename) if not config.flatten else export_filename
            metadata = FileMetadata(
                filename=export_filename,
                id=uuid,
                title=title,
                full_path=full_rel_path,
            )

        return export_path, metadata, None

    except Exception as e:
        return None, None, f"{file_path}: {e}"


def export_files(config: ExportConfig) -> tuple[ExportStats, list[FileMetadata]]:
    """
    Export all JSON files to the configured format.

    Args:
        config: Export configuration.

    Returns:
        Tuple of (export statistics, list of file metadata for Onyx format).
    """
    stats = ExportStats()
    file_metadata_list: list[FileMetadata] = []

    # Clean and create export directory
    if os.path.exists(EXPORT_DATA_DIR):
        shutil.rmtree(EXPORT_DATA_DIR)
    os.makedirs(EXPORT_DATA_DIR, exist_ok=True)

    source_files = collect_source_files(config)
    stats.total_files = len(source_files)

    for file_path in source_files:
        exported_path, metadata, error = export_single_file(file_path, config)
        if error:
            if exported_path is None:
                stats.skipped_missing_fields += 1
            stats.errors.append(error)
            continue

        stats.exported_files += 1
        if metadata:
            file_metadata_list.append(metadata)

    return stats, file_metadata_list


def create_zip_archives(
    config: ExportConfig,
    metadata_list: list[FileMetadata] | None = None,
) -> list[str]:
    """
    Create zip archives from the exported files.

    Args:
        config: Export configuration.
        metadata_list: Optional list of file metadata for Onyx format.

    Returns:
        List of created zip file paths.
    """
    zip_files: list[str] = []

    if not config.create_zip:
        return zip_files

    # Get all exported files organized by source
    export_ext = ".json" if config.export_format == "json" else ".txt"
    files_by_source: dict[str, list[str]] = {}

    for root, _dirs, files in os.walk(EXPORT_DATA_DIR):
        for filename in files:
            if not filename.endswith(export_ext):
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(root, EXPORT_DATA_DIR)
            source = rel_path.split(os.sep)[0] if rel_path != "." else "root"

            if source not in files_by_source:
                files_by_source[source] = []
            files_by_source[source].append(file_path)

    # Determine zip creation strategy
    if config.split_by_source:
        # Create one zip per source
        for source, files in sorted(files_by_source.items()):
            if config.max_files_per_zip:
                # Split source into multiple zips if needed
                for i, chunk_start in enumerate(
                    range(0, len(files), config.max_files_per_zip), start=1
                ):
                    chunk = files[chunk_start : chunk_start + config.max_files_per_zip]
                    zip_name = f"{source}_slice_{i:04d}.zip"
                    zip_path = os.path.join(EXPORT_DATA_DIR, zip_name)
                    _create_single_zip(zip_path, chunk, EXPORT_DATA_DIR, metadata_list)
                    zip_files.append(zip_path)
            else:
                zip_name = f"{source}.zip"
                zip_path = os.path.join(EXPORT_DATA_DIR, zip_name)
                _create_single_zip(zip_path, files, EXPORT_DATA_DIR, metadata_list)
                zip_files.append(zip_path)
    else:
        # Collect all files
        all_files: list[str] = []
        for files in files_by_source.values():
            all_files.extend(files)
        all_files.sort()

        if config.max_files_per_zip:
            # Split into multiple zips
            for i, chunk_start in enumerate(
                range(0, len(all_files), config.max_files_per_zip), start=1
            ):
                chunk = all_files[chunk_start : chunk_start + config.max_files_per_zip]
                zip_name = f"dataset_slice_{i:04d}.zip"
                zip_path = os.path.join(EXPORT_DATA_DIR, zip_name)
                _create_single_zip(zip_path, chunk, EXPORT_DATA_DIR, metadata_list)
                zip_files.append(zip_path)
        else:
            # Single zip for everything
            zip_path = os.path.join(EXPORT_DATA_DIR, "dataset.zip")
            _create_single_zip(zip_path, all_files, EXPORT_DATA_DIR, metadata_list)
            zip_files.append(zip_path)

    return zip_files


def _create_single_zip(
    zip_path: str,
    files: list[str],
    base_dir: str,
    metadata_list: list[FileMetadata] | None = None,
) -> None:
    """
    Create a single zip file from a list of files.

    Args:
        zip_path: Path for the zip file.
        files: List of file paths to include.
        base_dir: Base directory for relative paths in the zip.
        metadata_list: Optional list of file metadata for Onyx format.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            arcname = os.path.relpath(file_path, base_dir)
            zf.write(file_path, arcname)

        # Add .onyx_metadata.json if metadata is provided
        if metadata_list:
            # Build metadata lookup from full paths in this zip
            files_in_zip = {os.path.relpath(f, base_dir) for f in files}

            # Filter metadata to only include files in this zip (using full_path)
            # Output only filename, id, and title (not full_path)
            metadata_for_zip = [
                {"filename": m.filename, "id": m.id, "title": m.title}
                for m in metadata_list
                if m.full_path in files_in_zip
            ]

            if metadata_for_zip:
                metadata_json = json.dumps(metadata_for_zip, indent=2)
                zf.writestr(".onyx_metadata.json", metadata_json)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export generated data files to plain text format."
    )
    parser.add_argument(
        "--max-files",
        type=int,
        help="Maximum total number of files to export",
    )
    parser.add_argument(
        "--random-sample",
        action="store_true",
        help="Randomly sample files from the entire corpus (only applies with --max-files)",
    )
    parser.add_argument(
        "--flatten",
        action="store_true",
        help="Place all files at the top level with no directory structure",
    )
    parser.add_argument(
        "--sources",
        type=str,
        nargs="+",
        help="Source types to include (e.g., confluence slack). Defaults to all",
    )
    parser.add_argument(
        "--create-zip",
        action="store_true",
        help="Create zip file(s) of the exported data",
    )
    parser.add_argument(
        "--max-files-per-zip",
        type=int,
        help="Maximum files per zip; creates incremental slices when exceeded",
    )
    parser.add_argument(
        "--split-by-source",
        action="store_true",
        help="Create a separate zip file for each source type",
    )
    parser.add_argument(
        "--export-format",
        type=str,
        choices=["txt", "json"],
        default="txt",
        help="'txt' for plain text, 'json' for original format with metadata (default: txt)",
    )
    args = parser.parse_args()

    # Check for Onyx format from environment variable
    onyx_format = os.environ.get(ONYX_FORMAT_ENV_VAR, "").lower() in ("1", "true", "yes")

    config = ExportConfig(
        sources=args.sources,
        create_zip=args.create_zip,
        max_files_per_zip=args.max_files_per_zip,
        max_files=args.max_files,
        random_sample=args.random_sample,
        flatten=args.flatten,
        export_format=args.export_format,
        split_by_source=args.split_by_source,
        onyx_format=onyx_format,
    )

    print("=" * 50)
    print("Default Basic File Export")
    print("=" * 50)
    print()
    print(f"Source directory: {SOURCES_DIR}")
    print(f"Export directory: {EXPORT_DATA_DIR}")
    if config.sources:
        print(f"Filtering sources: {', '.join(config.sources)}")
    print(f"Create zip: {config.create_zip}")
    if config.max_files_per_zip:
        print(f"Max files per zip: {config.max_files_per_zip}")
    if config.max_files:
        print(f"Max files: {config.max_files}")
    if config.random_sample:
        print("Random sample: enabled")
    if config.flatten:
        print("Flatten: enabled (all files at top level)")
    print(f"Export format: {config.export_format}")
    if config.split_by_source:
        print("Split by source: enabled")
    if config.onyx_format:
        print("Onyx format: enabled (title in .onyx_metadata.json)")
    print()

    # Check if export directory already exists
    if directory_exists(EXPORT_DATA_DIR):
        print(f"Warning: {EXPORT_DATA_DIR}/ already exists.", flush=True)
        if not confirm_yes_no("Wipe directory and proceed with export?", default=False):
            print("Export cancelled.")
            return
        print()  # Blank line after confirmation

    # Export files
    print("Exporting files...", flush=True)
    stats, metadata_list = export_files(config)

    # Copy questions file if it exists
    if os.path.exists(QUESTIONS_PATH):
        questions_dest = os.path.join(EXPORT_DATA_DIR, os.path.basename(QUESTIONS_PATH))
        shutil.copy2(QUESTIONS_PATH, questions_dest)
        print(f"Copied {QUESTIONS_PATH} → {questions_dest}")
    else:
        print(f"Warning: {QUESTIONS_PATH} not found, skipping questions export.")

    print()
    print("Export Statistics:")
    print(f"  Total JSON files found: {stats.total_files}")
    print(f"  Successfully exported: {stats.exported_files}")
    print(f"  Skipped (missing fields): {stats.skipped_missing_fields}")

    if stats.errors:
        print()
        print(f"Errors ({len(stats.errors)}):")
        for error in stats.errors[:10]:
            print(f"  - {error}")
        if len(stats.errors) > 10:
            print(f"  ... and {len(stats.errors) - 10} more errors")

    # Create zip archives if requested
    if config.create_zip:
        print()
        print("Creating zip archives...")
        # Pass metadata list if in Onyx format
        zip_metadata = metadata_list if config.onyx_format else None
        zip_files = create_zip_archives(config, zip_metadata)
        print(f"Created {len(zip_files)} zip file(s):")
        for zf in zip_files:
            size_mb = os.path.getsize(zf) / (1024 * 1024)
            print(f"  - {zf} ({size_mb:.2f} MB)")
        if config.onyx_format:
            print("  (each zip includes .onyx_metadata.json)")

    print()
    print("Export complete.")


if __name__ == "__main__":
    main()
