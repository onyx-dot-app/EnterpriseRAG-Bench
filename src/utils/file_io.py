"""File I/O utilities."""

import json
import os
import tempfile
import unicodedata
from typing import Any


_HOMOGLYPH_MAP: dict[str, str] = {
    # Cyrillic lowercase → Latin
    "\u0430": "a",  # а
    "\u0441": "c",  # с
    "\u0435": "e",  # е
    "\u043e": "o",  # о
    "\u0440": "p",  # р
    "\u0445": "x",  # х
    "\u0443": "y",  # у
    "\u0456": "i",  # і
    "\u0458": "j",  # ј
    "\u0455": "s",  # ѕ
    # Cyrillic uppercase → Latin
    "\u0410": "A",  # А
    "\u0412": "B",  # В
    "\u0421": "C",  # С
    "\u0415": "E",  # Е
    "\u041d": "H",  # Н
    "\u041a": "K",  # К
    "\u041c": "M",  # М
    "\u041e": "O",  # О
    "\u0420": "P",  # Р
    "\u0422": "T",  # Т
    "\u0425": "X",  # Х
    "\u0423": "Y",  # У
}


def sanitize_filename(filename: str) -> str:
    """Replace non-ASCII characters in a filename with their closest ASCII equivalents.

    First maps common homoglyphs (e.g., Cyrillic 'с' → Latin 'c'), then uses
    NFKD normalization to decompose accented characters, and finally strips any
    remaining non-ASCII bytes.

    Only sanitizes the filename itself, not directory separators.

    Args:
        filename: The filename (basename only, no directory path).

    Returns:
        The sanitized ASCII-safe filename.
    """
    # Replace known homoglyphs first
    mapped = "".join(_HOMOGLYPH_MAP.get(ch, ch) for ch in filename)
    # NFKD decomposition handles accented characters (é → e + combining accent)
    normalized = unicodedata.normalize("NFKD", mapped)
    ascii_bytes = normalized.encode("ascii", "ignore")
    return ascii_bytes.decode("ascii")


def sanitize_path(path: str) -> str:
    """Sanitize all components of a file path to ASCII-safe names.

    Applies sanitize_filename to each component of the path while preserving
    the directory structure (separators).

    Args:
        path: A relative file path (e.g., "slack/sales/filename.json").

    Returns:
        The path with all components sanitized.
    """
    parts = path.replace("\\", "/").split("/")
    return "/".join(sanitize_filename(part) for part in parts)


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
        result: dict[str, Any] = json.load(f)
    return result


def write_json_file(path: str, data: dict[str, Any]) -> None:
    """Write data to a JSON file with standard formatting using atomic write.

    Uses atomic write (write to temp file, then rename) to prevent corruption
    if the process is killed during write. Creates parent directories if they
    don't exist.

    Args:
        path: Path to the JSON file to write.
        data: The data to write as JSON.
    """
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    # Write to a temp file in the same directory (same filesystem for atomic rename)
    fd, temp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=".write_",
        dir=parent_dir if parent_dir else ".",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        # Atomic rename - if process is killed here, temp file is orphaned but original is intact
        os.replace(temp_path, path)
    except Exception:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


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
