"""Retrieval over the historical-threads chromadb collection.

Two-step recall: similarity search returns the top reply units, then we
re-pull every reply for each surfaced submission_id so the CSR sees the
full thread context (sorted by reply_index).
"""
from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from chromadb.api.shared_system_client import SharedSystemClient
from langchain_chroma import Chroma

from src.config import get_embeddings


def _decode_attachments(raw: Any) -> list[dict[str, Any]]:
    """Parse the JSON-encoded attachments_json metadata field."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [dict(entry) for entry in raw if isinstance(entry, dict)]
    try:
        decoded = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    if isinstance(decoded, list):
        return [dict(entry) for entry in decoded if isinstance(entry, dict)]
    return []

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHROMA_DIR = _PROJECT_ROOT / "data" / "processed" / "chroma_historical_threads"
COLLECTION_NAME = "historical_threads_v1"


@lru_cache(maxsize=1)
def get_threads_store() -> Chroma:
    SharedSystemClient.clear_system_cache()
    return Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
        embedding_function=get_embeddings(),
    )


def _format_match(doc, score: float) -> dict[str, Any]:
    md = dict(doc.metadata or {})
    return {
        "submission_id": md.get("submission_id", ""),
        "reply_index": md.get("reply_index", 0),
        "reply_total": md.get("reply_total", 0),
        "submitted_at": md.get("submitted_at", ""),
        "reply_timestamp": md.get("reply_timestamp", ""),
        "sender_name": md.get("sender_name", ""),
        "institution": md.get("institution", ""),
        "reply_sender_name": md.get("reply_sender_name", ""),
        "reply_subject": md.get("reply_subject", ""),
        "service_of_interest": md.get("service_of_interest", ""),
        "products_of_interest": md.get("products_of_interest", ""),
        "has_customer_message": md.get("has_customer_message", False),
        "attachments": _decode_attachments(md.get("attachments_json")),
        "score": float(score),
        "page_content": doc.page_content,
    }


def _load_full_thread(store: Chroma, submission_id: str) -> list[dict[str, Any]]:
    """Return all reply units for one submission, sorted by reply_index."""
    raw = store.get(where={"submission_id": submission_id})
    docs = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []

    units = []
    for content, md in zip(docs, metadatas):
        md = dict(md or {})
        units.append(
            {
                "submission_id": md.get("submission_id", ""),
                "reply_index": int(md.get("reply_index", 0) or 0),
                "reply_total": int(md.get("reply_total", 0) or 0),
                "submitted_at": md.get("submitted_at", ""),
                "reply_timestamp": md.get("reply_timestamp", ""),
                "sender_name": md.get("sender_name", ""),
                "institution": md.get("institution", ""),
                "reply_sender_name": md.get("reply_sender_name", ""),
                "reply_subject": md.get("reply_subject", ""),
                "service_of_interest": md.get("service_of_interest", ""),
                "products_of_interest": md.get("products_of_interest", ""),
                "has_customer_message": md.get("has_customer_message", False),
                "attachments": _decode_attachments(md.get("attachments_json")),
                "page_content": content,
            }
        )
    units.sort(key=lambda u: u["reply_index"])
    return units


def retrieve_historical_threads(
    *,
    query: str,
    top_k: int = 8,
    thread_limit: int = 3,
    require_customer_message: bool = True,
) -> dict[str, Any]:
    """Return top reply hits + the full threads they belong to.

    require_customer_message=True excludes internal-team / orphan-followup
    rows from the initial similarity search (they have no real inquiry to
    match against). Set False for an unfiltered debug pass.
    """
    if not (query or "").strip():
        return {"matches": [], "threads": []}

    store = get_threads_store()

    where: dict[str, Any] | None = None
    if require_customer_message:
        where = {"has_customer_message": True}

    raw_hits = store.similarity_search_with_relevance_scores(
        query=query,
        k=top_k,
        filter=where,
    )
    matches = [_format_match(doc, score) for doc, score in raw_hits]

    # Group hits by submission_id, preserving best-score order
    seen: dict[str, float] = {}
    for m in matches:
        sid = m["submission_id"]
        if not sid:
            continue
        if sid not in seen or m["score"] > seen[sid]:
            seen[sid] = m["score"]

    ranked_submissions = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)
    top_submissions = [sid for sid, _ in ranked_submissions[:thread_limit]]

    threads = []
    for sid in top_submissions:
        units = _load_full_thread(store, sid)
        if not units:
            continue
        threads.append(
            {
                "submission_id": sid,
                "best_score": seen[sid],
                "reply_count": len(units),
                "units": units,
            }
        )

    return {
        "matches": matches,
        "threads": threads,
    }


__all__ = [
    "CHROMA_DIR",
    "COLLECTION_NAME",
    "get_threads_store",
    "retrieve_historical_threads",
]
