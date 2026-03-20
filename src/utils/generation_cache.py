"""Thread-safe generation cache for consolidated JSON storage.

Replaces the numbered-file scheme in question_cache/ with single JSON files
in generation_cache/.
"""

import os
import threading
from typing import Any

from src.utils.file_io import load_json_file, write_json_file

GENERATION_CACHE_DIR = "generation_cache"


class GenerationCache:
    """Thread-safe cache backed by a single JSON file.

    The JSON file stores a dict with a single key mapping to a list of entries.
    Uses write_json_file() for atomic writes and a threading.Lock to protect
    the load-append-write cycle.
    """

    def __init__(self, filename: str, key: str) -> None:
        self._path = os.path.join(GENERATION_CACHE_DIR, filename)
        self._key = key
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return self._path

    @property
    def key(self) -> str:
        return self._key

    def load(self) -> list[dict[str, Any]]:
        """Load all entries from the cache file.

        Returns:
            List of entry dicts. Empty list if file doesn't exist.
        """
        if not os.path.exists(self._path):
            return []
        data = load_json_file(self._path)
        return data.get(self._key, [])

    def append(self, entry: dict[str, Any]) -> None:
        """Append a single entry to the cache file (thread-safe)."""
        with self._lock:
            entries = self.load()
            entries.append(entry)
            write_json_file(self._path, {self._key: entries})

    def write_all(self, entries: list[dict[str, Any]]) -> None:
        """Overwrite the cache with the given entries (thread-safe)."""
        with self._lock:
            write_json_file(self._path, {self._key: entries})

    def count(self) -> int:
        """Return the number of entries in the cache."""
        return len(self.load())


# Singleton instances
projects_cache = GenerationCache("projects.json", "projects")
completeness_cache = GenerationCache("completeness.json", "completeness")
duplications_cache = GenerationCache("duplications.json", "duplications")
