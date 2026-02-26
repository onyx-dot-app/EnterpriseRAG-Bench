"""File I/O utilities."""

import json
import os
from typing import Any


def load_file(path: str) -> str:
    """Load a file and return its contents.

    Args:
        path: Path to the file to load.

    Returns:
        The file contents as a string.

    Raises:
        ValueError: If the file is empty.
    """
    with open(path) as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"File at {path} is empty")
    return content


def load_json_file(path: str) -> dict[str, Any]:
    """Load a JSON file and return its contents.

    Args:
        path: Path to the JSON file to load.

    Returns:
        The parsed JSON data as a dictionary.
    """
    with open(path) as f:
        return json.load(f)


def write_json_file(path: str, data: dict[str, Any]) -> None:
    """Write data to a JSON file with standard formatting.

    Creates parent directories if they don't exist.

    Args:
        path: Path to the JSON file to write.
        data: The data to write as JSON.
    """
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def delete_file(path: str) -> bool:
    """Delete a file if it exists.

    Args:
        path: Path to the file to delete.

    Returns:
        True if file was deleted, False if it didn't exist.
    """
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
