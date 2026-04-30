"""Ingest historical HubSpot form-inquiry threads into a chromadb collection.

Reads from PostgreSQL `historical_threads` + `historical_thread_messages`,
which is the source of truth (loaded by scripts/import_historical_threads.py).
Each emitted Document is a (customer message, sales reply) pair — for every
sales-role message we look up the most recent preceding customer-role message
in the same thread.

Re-runnable: existing IDs are upserted, so this can be re-run after the user
appends more historical data.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from chromadb.api.shared_system_client import SharedSystemClient
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from src.config import get_embeddings  # noqa: E402
from src.services.service_documents import build_connection_string  # noqa: E402

ATTACHMENTS_CACHE_PATH = PROJECT_ROOT / "data" / "processed" / "hubspot_attachments_cache.json"
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

# Pulls every sales reply with its most recent preceding customer message and
# enough thread context to reproduce the per-row metadata the CSV ingest
# emitted. reply_index / reply_total are computed inline with window functions.
_PG_QUERY = """
    SELECT
        t.submission_id,
        t.contact_id,
        t.submitted_at,
        t.sender_name,
        t.sender_email AS email,
        t.institution,
        t.service_of_interest,
        t.products_of_interest,
        t.form_name,
        t.lifecycle_stage,
        m_sales.message_index,
        m_sales.timestamp AS reply_timestamp,
        m_sales.sender_name AS reply_sender_name,
        m_sales.sender_email AS reply_sender_email,
        m_sales.subject AS reply_subject,
        m_sales.direction AS reply_direction,
        m_sales.external_message_id AS reply_message_id,
        m_sales.body AS reply_message,
        m_sales.attachments AS reply_attachments,
        m_cust.body AS customer_message,
        m_cust.source AS customer_message_source,
        ROW_NUMBER() OVER (
            PARTITION BY t.thread_id
            ORDER BY m_sales.message_index
        ) AS reply_index,
        COUNT(*) OVER (PARTITION BY t.thread_id) AS reply_total
    FROM historical_threads t
    JOIN historical_thread_messages m_sales
        ON m_sales.thread_id = t.thread_id
       AND m_sales.role = 'sales'
    LEFT JOIN LATERAL (
        SELECT body, source
        FROM historical_thread_messages mc
        WHERE mc.thread_id = t.thread_id
          AND mc.role = 'customer'
          AND mc.message_index < m_sales.message_index
        ORDER BY mc.message_index DESC
        LIMIT 1
    ) m_cust ON TRUE
    ORDER BY t.thread_id, m_sales.message_index
"""


@lru_cache(maxsize=1)
def _load_attachments_cache() -> dict[str, dict]:
    if not ATTACHMENTS_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(ATTACHMENTS_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _resolve_attachments(file_ids: list[str] | None) -> list[dict[str, str | int]]:
    cache = _load_attachments_cache()
    out: list[dict[str, str | int]] = []
    for fid in file_ids or []:
        token = str(fid).strip()
        if not token:
            continue
        entry = cache.get(token) or {}
        out.append({
            "id": token,
            "name": entry.get("name") or "",
            "extension": entry.get("extension") or "",
            "type": entry.get("type") or "",
            "url": entry.get("url") or "",
            "size": entry.get("size") or 0,
            "status": entry.get("status") or "unresolved",
        })
    return out


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _row_to_document(row: dict[str, Any]) -> Document | None:
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
        page_content = f"Sales reply (no preceding customer message):\n{reply}"

    metadata: dict[str, str | int | bool] = {
        key: _scalar(row.get(key)) for key in METADATA_KEYS
    }
    metadata["has_customer_message"] = has_customer
    for int_key in ("reply_index", "reply_total"):
        try:
            metadata[int_key] = int(row.get(int_key) or 0)
        except (ValueError, TypeError):
            metadata[int_key] = 0

    attachments = _resolve_attachments(row.get("reply_attachments"))
    metadata["attachments_json"] = json.dumps(attachments, ensure_ascii=False) if attachments else ""
    metadata["attachment_count"] = len(attachments)

    return Document(page_content=page_content, metadata=metadata)


def _stable_id(metadata: dict) -> str:
    return f"{metadata['submission_id']}__{metadata['reply_index']}"


def _iter_documents(conn: psycopg.Connection[Any], *, limit: int | None) -> Iterable[Document]:
    sql = _PG_QUERY
    if limit is not None:
        sql = sql.rstrip().rstrip(";") + f"\n    LIMIT {int(limit)}"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        for row in cur:
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
    """Ingest PG rows into chromadb. Returns (rows_seen, docs_indexed)."""
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

    with psycopg.connect(build_connection_string()) as conn:
        for batch in _batched(_iter_documents(conn, limit=limit), batch_size):
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

    load_dotenv(PROJECT_ROOT / ".env")

    print(f"Source     : Postgres (historical_threads x historical_thread_messages)")
    print(f"Chroma dir : {CHROMA_DIR}")
    print(f"Collection : {COLLECTION_NAME}")
    print(f"Batch size : {args.batch_size}")
    print()

    rows, indexed = ingest(batch_size=args.batch_size, limit=args.limit)
    print()
    print(f"Done. rows_seen={rows} docs_indexed={indexed}")


if __name__ == "__main__":
    main()
