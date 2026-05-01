from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

from src.rag.vectorstore import get_vectorstore

_PRICING_METADATA_KEYS: tuple[str, ...] = (
    "price_usd",
    "price_usd_min",
    "price_usd_max",
    "pricing_tier",
    "unit",
    "unit_price_usd",
    "setup_fee_usd",
    "price_note",
)
_PRICE_MAGNITUDE_KEYS: tuple[str, ...] = (
    "price_usd",
    "price_usd_min",
    "price_usd_max",
    "unit_price_usd",
    "setup_fee_usd",
)
_EXCERPT_LENGTH = 240


def _is_pricing_chunk(chunk: Document) -> bool:
    """A chunk is pricing-bearing if it's tagged as ``pricing_overview`` or
    carries any pricing metadata field. Both signals come from the
    service-page ingestion pipeline (see service_page_ingestion.py)."""
    metadata = chunk.metadata or {}
    if str(metadata.get("section_type") or "") == "pricing_overview":
        return True
    return any(metadata.get(key) for key in _PRICING_METADATA_KEYS)


def _coerce_price(value: Any) -> Any:
    """Pricing fields are stored as strings in Chroma metadata; coerce to a
    number when possible so the panel/LLM gets `$50000` instead of `'50000'`."""
    if value in (None, ""):
        return None
    try:
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        return float(text) if "." in text else int(text)
    except (TypeError, ValueError):
        return str(value)


def _build_flyer_pricing_record(chunk: Document) -> dict[str, Any]:
    metadata = chunk.metadata or {}
    record: dict[str, Any] = {
        "_subsource": "service_flyer",
        "service_name": (
            metadata.get("service_name")
            or metadata.get("page_title")
            or ""
        ),
        "business_line": (
            metadata.get("business_line")
            or metadata.get("service_line")
            or ""
        ),
        "price": _coerce_price(metadata.get("price_usd")),
        "price_min": _coerce_price(metadata.get("price_usd_min")),
        "price_max": _coerce_price(metadata.get("price_usd_max")),
        "currency": "USD" if any(
            metadata.get(key) for key in _PRICE_MAGNITUDE_KEYS
        ) else None,
        "pricing_tier": metadata.get("pricing_tier") or "",
        "unit": metadata.get("unit") or "",
        "unit_price": _coerce_price(metadata.get("unit_price_usd")),
        "setup_fee": _coerce_price(metadata.get("setup_fee_usd")),
        "price_note": metadata.get("price_note") or "",
        "source_section": (
            metadata.get("section_title")
            or metadata.get("chunk_label")
            or ""
        ),
        "source_excerpt": (chunk.page_content or "").strip()[:_EXCERPT_LENGTH],
    }
    return record


def lookup_flyer_pricing(
    *,
    query: str,
    top_k: int = 3,
    candidate_pool: int = 10,
) -> list[dict[str, Any]]:
    """Embed-search the service-page Chroma store and return up to ``top_k``
    pricing-bearing chunks as flat record dicts.

    Why a thin path instead of reusing ``retrieve_chunks``: pricing chunks
    already carry strong metadata signal (``section_type ==
    "pricing_overview"`` or non-empty ``price_usd*``), so a direct
    similarity-search + post-filter is simpler and more predictable than
    the full retrieval pipeline (which is tuned for technical-doc reranking
    with query rewrite / business-line boost / etc.).

    We over-fetch ``candidate_pool`` then filter so we can still return
    up to ``top_k`` actual pricing chunks when the top similarity hits
    happen to be non-pricing sections of the same service page.
    """
    if not query.strip():
        return []
    try:
        store = get_vectorstore()
        hits = store.similarity_search_with_score(query, k=candidate_pool)
    except Exception:
        return []

    records: list[dict[str, Any]] = []
    for chunk, _score in hits:
        if not _is_pricing_chunk(chunk):
            continue
        records.append(_build_flyer_pricing_record(chunk))
        if len(records) >= top_k:
            break
    return records


__all__ = ["lookup_flyer_pricing"]
