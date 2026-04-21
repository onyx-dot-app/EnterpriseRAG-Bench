"""Index all source documents into OpenSearch for BM25 retrieval.

Builds a UUID index of all source documents, concatenates their title and
content into a single text field, and bulk-indexes them into OpenSearch.
Supports resume (skips already-indexed documents) and parallel bulk workers.

Usage:
    python -m src.scripts.answer_generation.index_document_bm25 [OPTIONS]

Args:
    --index-name        OpenSearch index name (default: "enterpriserag")
    --opensearch-url    OpenSearch server URL (default: "http://localhost:9200")
    --batch-size        Documents per bulk request (default: 500)
    --recreate          Drop and recreate index if it exists
    --skip-existing     Skip documents that already exist in OpenSearch
"""

from __future__ import annotations

import argparse
import os
import time

from opensearchpy import OpenSearch, helpers as os_helpers
from tqdm import tqdm

from src.paths import SOURCES_DIR
from src.utils.document_content import DocumentFieldError, extract_document_content
from src.utils.document_index import build_uuid_index
from src.utils.file_io import load_json_file

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_SETTINGS = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "analysis": {
            "analyzer": {
                "default": {
                    "type": "standard",
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "dataset_doc_uuid": {"type": "keyword"},
            "text": {"type": "text", "analyzer": "standard"},
        }
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_existing_doc_ids(client: OpenSearch, index_name: str) -> set[str]:
    """Scroll all existing dataset_doc_uuid values from the index."""
    existing: set[str] = set()
    if not client.indices.exists(index=index_name):
        return existing

    body = {"query": {"match_all": {}}, "_source": ["dataset_doc_uuid"]}
    resp = client.search(index=index_name, body=body, scroll="2m", size=1000)
    scroll_id = resp["_scroll_id"]
    hits = resp["hits"]["hits"]

    while hits:
        for hit in hits:
            uuid = hit["_source"].get("dataset_doc_uuid")
            if uuid:
                existing.add(uuid)
        resp = client.scroll(scroll_id=scroll_id, scroll="2m")
        scroll_id = resp["_scroll_id"]
        hits = resp["hits"]["hits"]

    client.clear_scroll(scroll_id=scroll_id)
    return existing


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Index source documents into OpenSearch for BM25 retrieval."
    )
    parser.add_argument(
        "--index-name", default="enterpriserag", help="OpenSearch index name"
    )
    parser.add_argument(
        "--opensearch-url",
        default="http://localhost:9200",
        help="OpenSearch server URL",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Documents per bulk request",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate index if it exists",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip documents that already exist in OpenSearch instead of overwriting",
    )
    args = parser.parse_args()

    start_time = time.time()

    # --- Build UUID index ---
    print("Building UUID index from source documents...")
    uuid_index = build_uuid_index(SOURCES_DIR)
    print(f"  Found {len(uuid_index)} documents with UUIDs")

    # --- Connect to OpenSearch ---
    client = OpenSearch(
        hosts=[args.opensearch_url],
        use_ssl=False,
        verify_certs=False,
    )

    # --- Create / recreate index ---
    if args.recreate and client.indices.exists(index=args.index_name):
        print(f"Dropping existing index '{args.index_name}'...")
        client.indices.delete(index=args.index_name)

    if not client.indices.exists(index=args.index_name):
        print(f"Creating index '{args.index_name}'...")
        client.indices.create(index=args.index_name, body=INDEX_SETTINGS)

    # --- Skip existing: get already-indexed IDs ---
    existing_ids: set[str] = set()
    if args.skip_existing and not args.recreate:
        print("Checking for already-indexed documents...")
        existing_ids = _get_existing_doc_ids(client, args.index_name)
        if existing_ids:
            print(f"  {len(existing_ids)} documents already indexed, will skip")

    # --- Prepare documents ---
    print("Preparing documents for indexing...")
    skipped = 0
    failed = 0
    actions: list[dict[str, object]] = []

    for dataset_doc_uuid, rel_path in tqdm(
        uuid_index.items(), desc="Reading docs", leave=False
    ):
        if dataset_doc_uuid in existing_ids:
            skipped += 1
            continue

        full_path = os.path.join(SOURCES_DIR, rel_path)
        try:
            doc_data = load_json_file(full_path)
            if not isinstance(doc_data, dict):
                failed += 1
                continue
            title, content = extract_document_content(doc_data)
        except (DocumentFieldError, Exception) as e:
            print(f"  Skipping {rel_path}: {e}")
            failed += 1
            continue

        text = f"{title}\n\n{content}"
        actions.append(
            {
                "_index": args.index_name,
                "_id": dataset_doc_uuid,
                "_source": {
                    "dataset_doc_uuid": dataset_doc_uuid,
                    "text": text,
                },
            }
        )

    print(
        f"  {len(actions)} documents to index, {skipped} skipped (already indexed), "
        f"{failed} failed to parse"
    )

    if not actions:
        print("Nothing to index.")
        return

    # --- Bulk index ---
    print(f"Bulk indexing (batch size {args.batch_size})...")
    indexed = 0
    error_count = 0

    for i in tqdm(range(0, len(actions), args.batch_size), desc="Batches"):
        batch = actions[i : i + args.batch_size]
        success, errors = os_helpers.bulk(client, batch, raise_on_error=False)
        indexed += success
        if errors:
            error_count += len(errors)
            for err in errors[:3]:
                print(f"  Bulk error: {err}")

    # Refresh index to make documents searchable
    client.indices.refresh(index=args.index_name)

    elapsed = time.time() - start_time
    print(
        f"\nDone. Indexed {indexed} documents in {elapsed:.1f}s "
        f"({skipped} skipped, {failed} failed to parse, {error_count} bulk errors)"
    )


if __name__ == "__main__":
    main()
