"""Utilities for indexing and loading source documents by dataset_doc_uuid."""

import os

from src.paths import SOURCES_DIR, UUID_INDEX_PATH
from src.utils.document_content import extract_document_content
from src.utils.file_io import load_json_file, write_json_file


DEFAULT_UUID_INDEX_CACHE_FILE = UUID_INDEX_PATH


def build_uuid_index(sources_dir: str = SOURCES_DIR) -> dict[str, str]:
    """Build a mapping of dataset_doc_uuid -> relative path from ``sources_dir``."""
    index: dict[str, str] = {}
    for root, _dirs, files in os.walk(sources_dir):
        for filename in files:
            if not filename.endswith(".json"):
                continue
            full_path = os.path.join(root, filename)
            try:
                doc = load_json_file(full_path)
                uuid = doc.get("dataset_doc_uuid")
                if uuid:
                    rel_path = os.path.relpath(full_path, sources_dir)
                    index[uuid] = rel_path
            except Exception:
                continue
    return index


def write_uuid_index_cache(cache_file: str, uuid_index: dict[str, str]) -> None:
    """Persist a UUID index cache file."""
    cache_dir = os.path.dirname(cache_file)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    write_json_file(cache_file, uuid_index)


def rebuild_uuid_index(
    cache_file: str = DEFAULT_UUID_INDEX_CACHE_FILE,
    sources_dir: str = SOURCES_DIR,
) -> dict[str, str]:
    """Rebuild the UUID index and overwrite the cache file."""
    print("  Building UUID index (this may take a moment)...")
    index = build_uuid_index(sources_dir=sources_dir)
    write_uuid_index_cache(cache_file, index)
    print(f"  Saved UUID index with {len(index)} entries to {cache_file}")
    return index


def load_or_build_uuid_index(
    cache_file: str = DEFAULT_UUID_INDEX_CACHE_FILE,
    sources_dir: str = SOURCES_DIR,
) -> dict[str, str]:
    """Load the UUID index cache or build it if it does not exist."""
    if os.path.exists(cache_file):
        print(f"  Loading UUID index from {cache_file}...")
        uuid_index = load_json_file(cache_file)
        if not isinstance(uuid_index, dict):
            raise ValueError(
                f"UUID index cache at {cache_file} did not contain a JSON object",
            )
        return uuid_index

    return rebuild_uuid_index(cache_file=cache_file, sources_dir=sources_dir)


def ensure_uuids_resolved(
    needed_uuids: set[str],
    uuid_index: dict[str, str] | None = None,
    cache_file: str = DEFAULT_UUID_INDEX_CACHE_FILE,
    sources_dir: str = SOURCES_DIR,
) -> dict[str, str]:
    """Load (or reuse) the UUID index, rebuilding once if any needed UUIDs are missing.

    Args:
        needed_uuids: Set of UUIDs that must be resolvable.
        uuid_index: Pre-loaded index to check first. If None, loads from cache.
        cache_file: Path to the UUID index cache file.
        sources_dir: Root directory of source documents.

    Returns:
        UUID index guaranteed to have been rebuilt if any needed UUIDs were
        initially missing. Prints a warning if some remain unresolvable even
        after the rebuild.
    """
    if uuid_index is None:
        uuid_index = load_or_build_uuid_index(
            cache_file=cache_file, sources_dir=sources_dir
        )

    missing = needed_uuids - uuid_index.keys()
    if not missing:
        return uuid_index

    print(f"  {len(missing)} UUID(s) missing from cache, rebuilding index...")
    uuid_index = rebuild_uuid_index(cache_file=cache_file, sources_dir=sources_dir)
    print(f"  UUID index now has {len(uuid_index)} entries.")

    still_missing = missing - uuid_index.keys()
    if still_missing:
        print(
            f"  Warning: {len(still_missing)} UUID(s) still unresolvable after rebuild."
        )

    return uuid_index


def load_document_json_by_uuid(
    dataset_doc_uuid: str,
    uuid_index: dict[str, str],
    sources_dir: str = SOURCES_DIR,
) -> dict:
    """Load a document JSON object by dataset_doc_uuid."""
    rel_path = uuid_index[dataset_doc_uuid]
    full_path = os.path.join(sources_dir, rel_path)
    doc_data = load_json_file(full_path)
    if not isinstance(doc_data, dict):
        raise ValueError(
            f"Document {dataset_doc_uuid} at {rel_path} did not contain a JSON object",
        )
    return doc_data


def load_document_content_by_uuid(
    dataset_doc_uuid: str,
    uuid_index: dict[str, str],
    sources_dir: str = SOURCES_DIR,
) -> tuple[str, str]:
    """Load extracted title/content for a document by dataset_doc_uuid."""
    doc_data = load_document_json_by_uuid(
        dataset_doc_uuid=dataset_doc_uuid,
        uuid_index=uuid_index,
        sources_dir=sources_dir,
    )
    return extract_document_content(doc_data)
