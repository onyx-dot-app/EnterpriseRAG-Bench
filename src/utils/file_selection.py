"""Utilities for selecting files from the sources directory."""

import os
import random

from src.paths import SOURCES_DIR


def dir_has_json_files(dir_path: str) -> bool:
    """
    Check if a directory has any JSON files anywhere underneath it.

    Args:
        dir_path: Absolute path to the directory.

    Returns:
        True if there are JSON files under this directory, False otherwise.
    """
    for _root, _dirs, files in os.walk(dir_path):
        for filename in files:
            if filename.endswith(".json"):
                return True
    return False


def select_random_file_hierarchical(base_dir: str | None = None) -> str | None:
    """
    Select a random JSON file using hierarchical random walk.

    At each directory level, lists subdirs and JSON files, filters out
    subdirs with no JSON files underneath, then picks randomly with equal
    probability between remaining items. If a file is picked, returns it.
    If a dir is picked, recurses into it.

    Args:
        base_dir: Absolute path to the directory to start from.
            Defaults to SOURCES_DIR if not provided.

    Returns:
        Path to a JSON file relative to SOURCES_DIR, or None if no files found.
    """
    if base_dir is None:
        base_dir = SOURCES_DIR

    try:
        entries = os.listdir(base_dir)
    except OSError:
        return None

    # Separate into subdirs and JSON files
    subdirs = []
    json_files = []

    for entry in entries:
        full_path = os.path.join(base_dir, entry)
        if os.path.isdir(full_path):
            # Only include dirs that have JSON files underneath
            if dir_has_json_files(full_path):
                subdirs.append(entry)
        elif entry.endswith(".json") and os.path.isfile(full_path):
            json_files.append(entry)

    # Combine valid options
    options = subdirs + json_files

    if not options:
        return None

    # Pick randomly with equal probability
    choice = random.choice(options)
    full_choice_path = os.path.join(base_dir, choice)

    if os.path.isdir(full_choice_path):
        # Recurse into the directory
        return select_random_file_hierarchical(full_choice_path)
    else:
        # It's a file - return relative path
        return os.path.relpath(full_choice_path, SOURCES_DIR)


def count_json_files(base_dir: str | None = None) -> int:
    """
    Count total JSON files in a directory.

    Args:
        base_dir: Directory to count files in. Defaults to SOURCES_DIR.

    Returns:
        Number of .json files in the directory tree.
    """
    if base_dir is None:
        base_dir = SOURCES_DIR

    count = 0
    for _root, _dirs, files in os.walk(base_dir):
        for filename in files:
            if filename.endswith(".json"):
                count += 1
    return count
