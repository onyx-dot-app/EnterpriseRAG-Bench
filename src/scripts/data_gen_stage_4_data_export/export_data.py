"""Export generated data to plain text or JSON files with optional zip packaging.

Converts the internal JSON source documents into plain text or JSON files suitable for
external consumption. Supports filtering by source type, random sampling, flattening
directory structure, and creating zip archives with optional per-source splitting.

Usage:
    python -m src.scripts.data_gen_stage_4_data_export.export_data [OPTIONS]

Args:
    --max-files              Maximum total number of files to export
    --random-sample          Randomly sample files (requires --max-files)
    --flatten-within-sources Flatten files within each source directory
    --sources                Source types to include (default: all)
    --dsid-file              Path to a text file with dataset_doc_uuids (one per line)
    --create-zip             Create zip file(s) of exported data
    --zip-name               Custom name for the output zip file (single-zip only)
    --max-files-per-zip      Maximum files per zip; creates slices when exceeded
    --split-by-source        Create a separate zip file per source type
    --export-format          Export format: "txt" or "json" (default: "txt")
"""

import argparse
import json
import os
import random
import shutil
import zipfile

from tqdm import tqdm

from pydantic import BaseModel

from src.paths import EXPORT_DATA_DIR, QUESTIONS_PATH, SOURCES_DIR
from src.utils import (
    confirm_yes_no,
    DocumentFieldError,
    extract_document_content,
    load_json_file,
    sanitize_filename,
)
from src.utils.document_index import ensure_uuids_resolved


# Environment variable to enable Onyx metadata format
ONYX_FORMAT_ENV_VAR = "EXPORT_IN_ONYX_FORMAT"


class ExportConfig(BaseModel):
    """Configuration for the export process."""

    sources: list[str] | None = None
    dsid_file: str | None = None
    create_zip: bool = False
    zip_name: str | None = None
    max_files_per_zip: int | None = None
    max_files: int | None = None
    random_sample: bool = False
    flatten_within_sources: bool = False
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
    return sanitize_filename(f"{uuid}__{base_name}.txt")


def load_dsid_file(dsid_file: str) -> set[str]:
    """
    Load dataset_doc_uuids from a text file (one per line).

    Args:
        dsid_file: Path to the text file.

    Returns:
        Set of non-empty dsid strings.
    """
    with open(dsid_file, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def collect_source_files(config: ExportConfig) -> list[str]:
    """
    Collect all JSON file paths from the source directories.

    When config.dsid_file is set, uses the UUID index to resolve only
    the specified dataset_doc_uuids to file paths.

    Args:
        config: Export configuration (uses sources and dsid_file filters).

    Returns:
        List of absolute file paths to JSON files.
    """
    if config.dsid_file:
        dsids = load_dsid_file(config.dsid_file)
        print(f"Loaded {len(dsids)} dsid(s) from {config.dsid_file}")
        uuid_index = ensure_uuids_resolved(dsids)
        all_files: list[str] = []
        missing: list[str] = []
        for dsid in sorted(dsids):
            rel_path = uuid_index.get(dsid)
            if rel_path:
                all_files.append(os.path.join(SOURCES_DIR, rel_path))
            else:
                missing.append(dsid)
        if missing:
            print(f"Warning: {len(missing)} dsid(s) not found in sources:")
            for dsid in missing[:10]:
                print(f"  - {dsid}")
            if len(missing) > 10:
                print(f"  ... and {len(missing) - 10} more")
        return all_files

    source_dirs = os.listdir(SOURCES_DIR)
    if config.sources:
        source_dirs = [s for s in source_dirs if s in config.sources]

    all_files = []
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

        if config.flatten_within_sources:
            # Flatten into export_data/{source}/ with no deeper subdirectories
            source_name = rel_path.split(os.sep)[0]
            export_subdir = os.path.join(EXPORT_DATA_DIR, source_name)
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
            if config.flatten_within_sources:
                source_name = rel_path.split(os.sep)[0]
                full_rel_path = os.path.join(source_name, export_filename)
            else:
                full_rel_path = os.path.join(rel_path, export_filename)
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

    for file_path in tqdm(source_files, desc="Exporting files", unit="file"):
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
    include_exts = {export_ext, ".jsonl"}
    files_by_source: dict[str, list[str]] = {}

    for root, _dirs, files in os.walk(EXPORT_DATA_DIR):
        for filename in files:
            if not any(filename.endswith(ext) for ext in include_exts):
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(root, EXPORT_DATA_DIR)
            source = rel_path.split(os.sep)[0] if rel_path != "." else "root"

            if source not in files_by_source:
                files_by_source[source] = []
            files_by_source[source].append(file_path)

    # Collect all zip tasks as (zip_path, file_list) pairs
    zip_tasks: list[tuple[str, list[str]]] = []

    if config.split_by_source:
        for source, files in sorted(files_by_source.items()):
            if config.max_files_per_zip:
                for i, chunk_start in enumerate(
                    range(0, len(files), config.max_files_per_zip), start=1
                ):
                    chunk = files[chunk_start : chunk_start + config.max_files_per_zip]
                    task_zip_name = f"{source}_slice_{i:04d}.zip"
                    zip_tasks.append(
                        (os.path.join(EXPORT_DATA_DIR, task_zip_name), chunk)
                    )
            else:
                task_zip_name = f"{source}.zip"
                zip_tasks.append((os.path.join(EXPORT_DATA_DIR, task_zip_name), files))
    else:
        all_files: list[str] = []
        for files in files_by_source.values():
            all_files.extend(files)
        all_files.sort()

        if config.max_files_per_zip:
            for i, chunk_start in enumerate(
                range(0, len(all_files), config.max_files_per_zip), start=1
            ):
                chunk = all_files[chunk_start : chunk_start + config.max_files_per_zip]
                task_zip_name = f"dataset_slice_{i:04d}.zip"
                zip_tasks.append((os.path.join(EXPORT_DATA_DIR, task_zip_name), chunk))
        else:
            default_name = "all_documents.zip"
            single_zip_name = config.zip_name or default_name
            zip_tasks.append(
                (os.path.join(EXPORT_DATA_DIR, single_zip_name), all_files)
            )

    # --zip-name is only valid when producing a single zip
    if config.zip_name and len(zip_tasks) > 1:
        raise ValueError(
            "--zip-name cannot be used when multiple zip files are produced "
            "(from --split-by-source or --max-files-per-zip). "
            "Remove --zip-name or adjust options to produce a single zip."
        )

    # Single zip: show per-file progress. Multiple zips: show per-zip progress.
    if len(zip_tasks) == 1:
        zip_path, task_files = zip_tasks[0]
        _create_single_zip(
            zip_path,
            task_files,
            EXPORT_DATA_DIR,
            metadata_list,
            show_file_progress=True,
        )
        zip_files.append(zip_path)
    else:
        for zip_path, task_files in tqdm(
            zip_tasks, desc="Creating zip archives", unit="zip"
        ):
            _create_single_zip(zip_path, task_files, EXPORT_DATA_DIR, metadata_list)
            zip_files.append(zip_path)

    return zip_files


def _create_single_zip(
    zip_path: str,
    files: list[str],
    base_dir: str,
    metadata_list: list[FileMetadata] | None = None,
    show_file_progress: bool = False,
) -> None:
    """
    Create a single zip file from a list of files.

    Args:
        zip_path: Path for the zip file.
        files: List of file paths to include.
        base_dir: Base directory for relative paths in the zip.
        metadata_list: Optional list of file metadata for Onyx format.
        show_file_progress: Show per-file progress bar within this zip.
    """
    zip_name = os.path.basename(zip_path)
    file_iter = (
        tqdm(files, desc=f"Zipping {zip_name}", unit="file")
        if show_file_progress
        else files
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in file_iter:
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
        "--flatten-within-sources",
        action="store_true",
        help="Flatten files within each source directory (e.g., export_data/slack/ with no subdirectories)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        nargs="+",
        help="Source types to include (e.g., confluence slack). Defaults to all",
    )
    parser.add_argument(
        "--dsid-file",
        type=str,
        help="Path to a text file with dataset_doc_uuids to export (one per line)",
    )
    parser.add_argument(
        "--create-zip",
        action="store_true",
        help="Create zip file(s) of the exported data",
    )
    parser.add_argument(
        "--zip-name",
        type=str,
        help="Custom filename for the output zip (single-zip mode only, e.g. 'my_export.zip')",
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

    # Onyx format only applies to txt exports
    onyx_format = args.export_format == "txt" and os.environ.get(
        ONYX_FORMAT_ENV_VAR, ""
    ).lower() in ("1", "true", "yes")

    config = ExportConfig(
        sources=args.sources,
        dsid_file=args.dsid_file,
        create_zip=args.create_zip,
        zip_name=args.zip_name,
        max_files_per_zip=args.max_files_per_zip,
        max_files=args.max_files,
        random_sample=args.random_sample,
        flatten_within_sources=args.flatten_within_sources,
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
    if config.dsid_file:
        print(f"DSID file: {config.dsid_file}")
    print(f"Create zip: {config.create_zip}")
    if config.max_files_per_zip:
        print(f"Max files per zip: {config.max_files_per_zip}")
    if config.max_files:
        print(f"Max files: {config.max_files}")
    if config.random_sample:
        print("Random sample: enabled")
    if config.flatten_within_sources:
        print(
            "Flatten within sources: enabled (files flattened under source directories)"
        )
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

    # Copy questions file before zip creation so it's included in the archive
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
    print(
        "This is the end of Dataset generation process. You can now use the zip files for your downstream tasks."
    )


if __name__ == "__main__":
    main()
