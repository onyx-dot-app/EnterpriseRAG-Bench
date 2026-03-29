"""Index all source documents into Qdrant using OpenAI text-embedding-3-large.

Builds a UUID index of all source documents, embeds their text content, and
upserts vectors into a Qdrant collection. Supports resume (skips already-indexed
documents) and parallel embedding workers.

Usage:
    python -m src.scripts.answer_generation.index_document_vectors [OPTIONS]

Args:
    --collection-name   Qdrant collection name (default: "industryrag")
    --qdrant-url        Qdrant server URL (default: "http://localhost:6333")
    --batch-size        Documents per embedding API call (default: 100)
    --max-tokens        Max tokens per document text before truncation (default: 8191)
    --parallelism       Parallel embedding batch workers (default: 4)
    --recreate          Drop and recreate collection if it exists
"""

from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import tiktoken
from openai import OpenAI, RateLimitError
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)
from tqdm import tqdm

from src.paths import SOURCES_DIR
from src.utils.document_content import DocumentFieldError, extract_document_content
from src.utils.document_index import build_uuid_index
from src.utils.file_io import load_json_file

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "text-embedding-3-large"
VECTOR_SIZE = 3072

_encoding = tiktoken.get_encoding("cl100k_base")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def truncate_text(text: str, max_tokens: int) -> str:
    """Truncate text to at most *max_tokens* tokens, breaking at a word boundary."""
    tokens = _encoding.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text
    truncated: str = _encoding.decode(tokens[:max_tokens])
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated


def uuid_to_point_id(dataset_doc_uuid: str) -> str:
    """Convert a ``dsid_<hex>`` UUID to a standard UUID string for Qdrant."""
    hex_str = dataset_doc_uuid.replace("dsid_", "")
    return (
        f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}"
        f"-{hex_str[16:20]}-{hex_str[20:]}"
    )


def _get_existing_point_ids(qdrant: QdrantClient, collection_name: str) -> set[str]:
    """Scroll all existing point IDs from the collection."""
    existing: set[str] = set()
    offset = None
    while True:
        result = qdrant.scroll(
            collection_name=collection_name,
            limit=1000,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        points, next_offset = result
        for point in points:
            existing.add(str(point.id))
        if next_offset is None:
            break
        offset = next_offset
    return existing


def _embed_and_upsert(
    openai_client: OpenAI,
    qdrant: QdrantClient,
    collection_name: str,
    batch: list[tuple[str, str, str]],
    max_retries: int = 3,
) -> int:
    """Embed a batch and upsert into Qdrant. Returns number of points upserted.

    Each item in *batch* is ``(dataset_doc_uuid, point_id, text)``.
    """
    texts = [item[2] for item in batch]

    # Embed with exponential backoff on rate limits
    for attempt in range(max_retries):
        try:
            response = openai_client.embeddings.create(
                model=EMBEDDING_MODEL, input=texts
            )
            break
        except RateLimitError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))

    points = []
    for item, embedding_data in zip(batch, response.data):
        dataset_doc_uuid, point_id, _ = item
        points.append(
            PointStruct(
                id=point_id,
                vector=embedding_data.embedding,
                payload={"dataset_doc_uuid": dataset_doc_uuid},
            )
        )

    qdrant.upsert(collection_name=collection_name, points=points)
    return len(points)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Index source documents into Qdrant with text-embedding-3-large."
    )
    parser.add_argument(
        "--collection-name", default="industryrag", help="Qdrant collection name"
    )
    parser.add_argument(
        "--qdrant-url", default="http://localhost:6333", help="Qdrant server URL"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Documents per embedding API call",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8191,
        help="Max tokens per document before truncation",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=4,
        help="Parallel embedding batch workers",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate collection if it exists",
    )
    args = parser.parse_args()

    start_time = time.time()

    # --- Build UUID index ---
    print("Building UUID index from source documents...")
    uuid_index = build_uuid_index(SOURCES_DIR)
    print(f"  Found {len(uuid_index)} documents with UUIDs")

    # --- Connect to Qdrant ---
    qdrant = QdrantClient(url=args.qdrant_url)

    # --- Create / recreate collection ---
    collections = [c.name for c in qdrant.get_collections().collections]
    if args.recreate and args.collection_name in collections:
        print(f"Dropping existing collection '{args.collection_name}'...")
        qdrant.delete_collection(args.collection_name)
        collections.remove(args.collection_name)

    if args.collection_name not in collections:
        print(f"Creating collection '{args.collection_name}'...")
        qdrant.create_collection(
            collection_name=args.collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        qdrant.create_payload_index(
            collection_name=args.collection_name,
            field_name="dataset_doc_uuid",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    # --- Resume: get already-indexed IDs ---
    existing_ids: set[str] = set()
    if not args.recreate:
        print("Checking for already-indexed documents...")
        existing_ids = _get_existing_point_ids(qdrant, args.collection_name)
        if existing_ids:
            print(f"  {len(existing_ids)} documents already indexed, will skip")

    # --- Prepare documents ---
    print("Preparing documents for embedding...")
    skipped = 0
    failed = 0
    batch: list[tuple[str, str, str]] = []
    all_batches: list[list[tuple[str, str, str]]] = []

    for dataset_doc_uuid, rel_path in uuid_index.items():
        point_id = uuid_to_point_id(dataset_doc_uuid)
        if point_id in existing_ids:
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
        text = truncate_text(text, args.max_tokens)
        batch.append((dataset_doc_uuid, point_id, text))

        if len(batch) >= args.batch_size:
            all_batches.append(batch)
            batch = []

    if batch:
        all_batches.append(batch)

    total_to_index = sum(len(b) for b in all_batches)
    print(
        f"  {total_to_index} documents to index, {skipped} skipped (already indexed), "
        f"{failed} failed to parse"
    )

    if not all_batches:
        print("Nothing to index.")
        return

    # --- Parallel embed + upsert ---
    openai_client = OpenAI(api_key=os.environ.get("LLM_API_KEY"))
    indexed = 0

    print(f"Embedding and upserting ({args.parallelism} workers)...")
    with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
        futures = {
            executor.submit(
                _embed_and_upsert,
                openai_client,
                qdrant,
                args.collection_name,
                b,
            ): i
            for i, b in enumerate(all_batches)
        }
        with tqdm(total=len(all_batches), desc="Batches") as pbar:
            for future in as_completed(futures):
                try:
                    indexed += future.result()
                except Exception as e:
                    batch_idx = futures[future]
                    print(f"\n  Batch {batch_idx} failed: {e}")
                pbar.update(1)

    elapsed = time.time() - start_time
    print(
        f"\nDone. Indexed {indexed} documents in {elapsed:.1f}s "
        f"({skipped} skipped, {failed} failed to parse)"
    )


if __name__ == "__main__":
    main()
