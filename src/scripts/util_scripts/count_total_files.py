"""Utility script to count JSON files in the sources directory.

Walks the generated_data/sources/ tree and displays a per-source-type breakdown of
JSON file counts in a formatted table, sorted by count descending.

Usage:
    python -m src.scripts.util_scripts.count_total_files

No arguments.
"""

import os
from collections import Counter

from src.paths import SOURCES_DIR


def count_json_files_per_source() -> dict[str, int]:
    """
    Count JSON files per source type in the sources directory.

    Returns:
        Dict mapping source type name to count of .json files.
    """
    counts: Counter[str] = Counter()

    if not os.path.exists(SOURCES_DIR):
        return dict(counts)

    for root, _dirs, files in os.walk(SOURCES_DIR):
        for filename in files:
            if filename.endswith(".json"):
                # Get the top-level source type
                rel_path = os.path.relpath(root, SOURCES_DIR)
                source_type = rel_path.split(os.sep)[0]
                counts[source_type] += 1

    return dict(counts)


def main() -> None:
    print("JSON File Count by Source")
    print("=" * 40)

    if not os.path.exists(SOURCES_DIR):
        print(f"Sources directory not found: {SOURCES_DIR}")
        return

    counts = count_json_files_per_source()

    if not counts:
        print("No JSON files found.")
        return

    # Sort by count descending
    sorted_counts = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    # Find max source name length for alignment
    max_name_len = max(len(name) for name in counts.keys())

    for source_type, count in sorted_counts:
        print(f"  {source_type:<{max_name_len}}  {count:>6,}")

    print("-" * 40)
    total = sum(counts.values())
    print(f"  {'Total':<{max_name_len}}  {total:>6,}")


if __name__ == "__main__":
    main()
