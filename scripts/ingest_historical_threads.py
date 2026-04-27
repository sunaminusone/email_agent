"""Ingest historical HubSpot form-inquiry threads into a chromadb collection.

Each row of data/processed/hubspot_form_inquiries_long.csv is one sales reply
unit (with the customer message that triggered it). We embed each row as a
Q+A pair and store enough metadata to (a) filter at retrieval time by service
or product and (b) regroup hits back into full threads at display time.

Re-runnable: existing IDs are upserted, so this can be re-run after the user
appends more historical data.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable

from chromadb.api.shared_system_client import SharedSystemClient
from langchain_chroma import Chroma
from langchain_core.documents import Document

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_embeddings  # noqa: E402

CSV_PATH = PROJECT_ROOT / "data" / "processed" / "hubspot_form_inquiries_long.csv"
CHROMA_DIR = PROJECT_ROOT / "data" / "processed" / "chroma_historical_threads"
COLLECTION_NAME = "historical_threads_v1"

METADATA_KEYS = (
    "submission_id",
    "contact_id",
    "submitted_at",
    "sender_name",
    "email",
    "institution",
    "customer_message_source",
    "service_of_interest",
    "products_of_interest",
    "form_name",
    "lifecycle_stage",
    "reply_index",
    "reply_total",
    "reply_timestamp",
    "reply_sender_name",
    "reply_sender_email",
    "reply_subject",
    "reply_direction",
    "reply_message_id",
)


def _row_to_document(row: dict[str, str]) -> Document | None:
    reply = (row.get("reply_message") or "").strip()
    if not reply:
        return None

    customer = (row.get("customer_message") or "").strip()
    has_customer = bool(customer)

    if has_customer:
        page_content = (
            "Customer message:\n"
            f"{customer}\n\n"
            "---\n\n"
            "Sales reply:\n"
            f"{reply}"
        )
    else:
        # Salesperson follow-up with no customer message in between, OR an
        # internal-team email. Embed reply alone; downstream can filter via
        # has_customer_message metadata if quality demands.
        page_content = f"Sales reply (no preceding customer message):\n{reply}"

    metadata: dict[str, str | int | bool] = {
        key: (row.get(key) or "") for key in METADATA_KEYS
    }
    metadata["has_customer_message"] = has_customer
    # Coerce numeric-ish fields for chromadb filtering
    for int_key in ("reply_index", "reply_total"):
        try:
            metadata[int_key] = int(metadata[int_key]) if metadata[int_key] != "" else 0
        except (ValueError, TypeError):
            metadata[int_key] = 0

    return Document(page_content=page_content, metadata=metadata)


def _stable_id(metadata: dict) -> str:
    return f"{metadata['submission_id']}__{metadata['reply_index']}"


def _iter_documents(csv_path: Path) -> Iterable[Document]:
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            doc = _row_to_document(row)
            if doc is not None:
                yield doc


def _batched(iterable: Iterable, batch_size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def ingest(*, batch_size: int = 200, limit: int | None = None) -> tuple[int, int]:
    """Ingest CSV rows into chromadb. Returns (rows_seen, docs_indexed)."""
    embeddings = get_embeddings()
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    SharedSystemClient.clear_system_cache()
    store = Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
    )

    rows_seen = 0
    docs_indexed = 0

    docs_iter = _iter_documents(CSV_PATH)
    if limit is not None:
        from itertools import islice
        docs_iter = islice(docs_iter, limit)

    for batch in _batched(docs_iter, batch_size):
        rows_seen += len(batch)
        ids = [_stable_id(d.metadata) for d in batch]
        store.add_documents(batch, ids=ids)
        docs_indexed += len(batch)
        print(f"  indexed {docs_indexed} docs...", flush=True)

    return rows_seen, docs_indexed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap rows ingested (smoke test).")
    args = parser.parse_args()

    print(f"Source CSV : {CSV_PATH}")
    print(f"Chroma dir : {CHROMA_DIR}")
    print(f"Collection : {COLLECTION_NAME}")
    print(f"Batch size : {args.batch_size}")
    print()

    rows, indexed = ingest(batch_size=args.batch_size, limit=args.limit)
    print()
    print(f"Done. rows_seen={rows} docs_indexed={indexed}")


if __name__ == "__main__":
    main()
