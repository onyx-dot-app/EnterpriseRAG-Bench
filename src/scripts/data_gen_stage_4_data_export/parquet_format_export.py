"""Export generated documents to Parquet format for HuggingFace dataset publishing.

Walks the source directories and converts each JSON document into a row with
doc_id, source_type, title, and content columns. The result is written as a
single Parquet file to the export directory.

Usage:
    python -m src.scripts.data_gen_stage_4_data_export.parquet_format_export [OPTIONS]

Args:
    --output    Output Parquet file path (default: export_data/documents.parquet)
    --sources   Source types to include (default: all)
"""

import argparse
import os

import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

from src.paths import EXPORT_DATA_DIR, SOURCES_DIR
from src.utils import (
    DocumentFieldError,
    extract_document_content,
    load_json_file,
)


def collect_source_files(sources: list[str] | None) -> list[str]:
    """Collect all JSON file paths from the source directories.

    Args:
        sources: Source types to include, or None for all.

    Returns:
        List of absolute file paths to JSON files.
    """
    source_dirs = os.listdir(SOURCES_DIR)
    if sources:
        source_dirs = [s for s in source_dirs if s in sources]

    all_files: list[str] = []
    for source in sorted(source_dirs):
        source_path = os.path.join(SOURCES_DIR, source)
        if not os.path.isdir(source_path):
            continue
        for root, _dirs, files in os.walk(source_path):
            for filename in files:
                if filename.endswith(".json"):
                    all_files.append(os.path.join(root, filename))

    return all_files


def get_source_type(file_path: str) -> str:
    """Extract source type from a file path (top-level dir under SOURCES_DIR).

    Args:
        file_path: Absolute path to a source JSON file.

    Returns:
        The source type string (e.g. "slack", "confluence").
    """
    rel_path = os.path.relpath(file_path, SOURCES_DIR)
    return rel_path.split(os.sep)[0]


def export_to_parquet(
    output_path: str,
    sources: list[str] | None,
) -> None:
    """Export all source documents to a single Parquet file.

    Args:
        output_path: Path for the output Parquet file.
        sources: Source types to include, or None for all.
    """
    source_files = collect_source_files(sources)
    print(f"Found {len(source_files)} JSON files to export")

    doc_ids: list[str] = []
    source_types: list[str] = []
    titles: list[str] = []
    contents: list[str] = []
    skipped = 0

    for file_path in tqdm(source_files, desc="Processing documents", unit="doc"):
        try:
            data = load_json_file(file_path)
        except Exception:
            skipped += 1
            continue

        if "dataset_doc_uuid" not in data:
            skipped += 1
            continue

        try:
            title, content = extract_document_content(data)
        except DocumentFieldError:
            skipped += 1
            continue

        doc_ids.append(data["dataset_doc_uuid"])
        source_types.append(get_source_type(file_path))
        titles.append(title)
        contents.append(content)

    table = pa.table(
        {
            "doc_id": pa.array(doc_ids, type=pa.string()),
            "source_type": pa.array(source_types, type=pa.string()),
            "title": pa.array(titles, type=pa.string()),
            "content": pa.array(contents, type=pa.string()),
        }
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    pq.write_table(table, output_path)

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print()
    print(f"Exported {len(doc_ids)} documents to {output_path} ({file_size_mb:.1f} MB)")
    if skipped:
        print(f"Skipped {skipped} files (missing fields or read errors)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export generated documents to Parquet format."
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(EXPORT_DATA_DIR, "documents.parquet"),
        help="Output Parquet file path (default: export_data/documents.parquet)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        nargs="+",
        help="Source types to include (e.g., confluence slack). Defaults to all",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("Parquet Format Export")
    print("=" * 50)
    print()
    print(f"Source directory: {SOURCES_DIR}")
    print(f"Output file: {args.output}")
    if args.sources:
        print(f"Filtering sources: {', '.join(args.sources)}")
    print()

    export_to_parquet(args.output, args.sources)


if __name__ == "__main__":
    main()
