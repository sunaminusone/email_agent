from __future__ import annotations

import re
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
    "total_price_usd",
    "price_note",
)
_PRICE_MAGNITUDE_KEYS: tuple[str, ...] = (
    "price_usd",
    "price_usd_min",
    "price_usd_max",
    "unit_price_usd",
    "setup_fee_usd",
    "total_price_usd",
)
_EXCERPT_LENGTH = 240

# Cell-type / platform keywords → canonical service_name (case-correct,
# matched against Chroma metadata) to bias toward when reranking
# similarity hits AND when issuing service-scoped focused searches.
# Currently scoped to the protein-expression family because that's
# where pure embedding similarity demonstrably can't disambiguate
# platform — e.g. yeast and E. coli flyer chunks outrank mammalian
# flyer chunks for HEK293 queries because those flyers have higher
# pricing-text density and embeddings don't model the domain fact
# "HEK293 == mammalian". This mirrors the biz_line boost the main
# retrieval pipeline already applies (which this thin path bypasses
# by design). Other service families (antibody / CAR-T / mRNA-LNP)
# can be added when we observe the same disambiguation failures.
_SUBSTRING_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("hek293", "hek 293", "mammalian"), "Mammalian Protein Expression"),
    (("e. coli", "e.coli", "bl21", "rosetta"), "E. coli Protein Expression"),
    (("pichia", "saccharomyces", "yeast"), "Yeast Protein Expression"),
    (("baculovirus", "insect cell"), "Baculovirus Protein Expression"),
)

# Tokens short or generic enough that substring matching would fire
# false positives ("cho" in "echo", "sf9" inside a hex blob); use word
# boundaries instead.
_WORD_BOUNDARY_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("cho",), "Mammalian Protein Expression"),
    (("ecoli",), "E. coli Protein Expression"),
    (("sf9", "sf21", "hi5"), "Baculovirus Protein Expression"),
)

# Companion chunk section types in priority order. Picked because they
# carry the quantitative / structural context a CSR (and the draft LLM)
# needs to reason about whether a primary pricing record actually
# answers the customer's ask — e.g. yield ranges decide whether a
# standard package can deliver a requested quantity.
_COMPANION_SECTION_PRIORITY: tuple[str, ...] = (
    "benchmark",          # yield ranges, throughput numbers
    "phase_overview",     # phase scale & cell-line info
    "plan_summary",       # multi-phase plan structure summary
    "workflow_overview",  # high-level workflow steps
)

_WORD_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _word_pattern(token: str) -> re.Pattern[str]:
    pattern = _WORD_PATTERN_CACHE.get(token)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(token) + r"\b", re.IGNORECASE)
        _WORD_PATTERN_CACHE[token] = pattern
    return pattern


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
        # Chroma metadata field naming is counterintuitive here: `service_line`
        # holds the human-readable label (e.g. "CAR-T/CAR-NK Development") and
        # `business_line` holds the slug (e.g. "car_t_car_nk"). Prefer the
        # readable form so the panel matches PG's business_line column.
        "business_line": (
            metadata.get("service_line")
            or metadata.get("business_line")
            or ""
        ),
        # Plan / phase context: many service flyers price each PHASE of a
        # multi-phase plan separately. Without surfacing plan_name /
        # phase_name / optional, the LLM cannot tell that two records are
        # different phases of the same plan rather than competing options,
        # and may incorrectly sum or misrepresent them.
        "plan_name": metadata.get("plan_name") or "",
        "phase_name": metadata.get("phase_name") or "",
        "phase_role": metadata.get("phase_role") or "",
        "optional": metadata.get("optional") or "",
        "duration_weeks": metadata.get("duration_weeks") or "",
        "plan_total_price": _coerce_price(metadata.get("total_price_usd")),
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


def _detect_preferred_services(query: str) -> set[str]:
    """Return the set of canonical service_name strings implied by
    cell-type / platform keywords in the query. Returned values match
    the case of ``service_name`` in Chroma metadata so they can be
    used for direct equality checks AND as Chroma metadata filters."""
    lowered = query.lower()
    matches: set[str] = set()
    for keywords, service_name in _SUBSTRING_HINTS:
        if any(kw in lowered for kw in keywords):
            matches.add(service_name)
    for keywords, service_name in _WORD_BOUNDARY_HINTS:
        if any(_word_pattern(kw).search(query) for kw in keywords):
            matches.add(service_name)
    return matches


def _rerank_by_preferred_service(
    hits: list[tuple[Document, float]],
    preferred_services: set[str],
) -> list[tuple[Document, float]]:
    """Stable rerank: chunks whose service_name matches a preferred
    service move to the front; relative order within each group is
    preserved so similarity still drives intra-group ordering."""
    if not preferred_services:
        return hits
    preferred: list[tuple[Document, float]] = []
    other: list[tuple[Document, float]] = []
    for hit in hits:
        chunk, _ = hit
        sn = (chunk.metadata or {}).get("service_name") or ""
        if sn in preferred_services:
            preferred.append(hit)
        else:
            other.append(hit)
    return preferred + other


def _focused_pricing_search(
    *,
    store: Any,
    query: str,
    service_name: str,
    pricing_chunks_wanted: int = 3,
    pool: int = 10,
) -> list[tuple[Document, float]]:
    """Run a metadata-filtered similarity search constrained to a single
    service flyer, then keep only pricing chunks. Returns up to
    ``pricing_chunks_wanted`` hits in similarity order.

    Why this exists: when a query implicates multiple platforms
    (e.g. "HEK293 vs CHO vs BL21") or contains keywords that pull
    other service flyers higher in the unfiltered pool ("antibody in
    CHO" surfaces antibody chunks first), the main candidate pool may
    contain non-pricing chunks for the preferred service while its
    pricing chunks live past the pool cap. A targeted per-service
    search guarantees pricing chunks for each detected preferred
    service have a chance to surface.
    """
    try:
        hits = store.similarity_search_with_score(
            query, k=pool, filter={"service_name": service_name}
        )
    except Exception:
        return []
    pricing: list[tuple[Document, float]] = []
    for hit in hits:
        if _is_pricing_chunk(hit[0]):
            pricing.append(hit)
            if len(pricing) >= pricing_chunks_wanted:
                break
    return pricing


def _chunk_dedup_key(chunk: Document) -> tuple[str, str]:
    md = chunk.metadata or {}
    return (md.get("service_name") or "", md.get("section_title") or "")


def _select_companion_chunk(
    *,
    service_name: str,
    ranked_hits: list[tuple[Document, float]],
    primary_keys: set[tuple[str, str]],
) -> Document | None:
    """Pick one context companion chunk for a service that already has
    a primary pricing record. Walks ``_COMPANION_SECTION_PRIORITY`` in
    order; within a tier picks the highest-similarity match. Returns
    ``None`` if no eligible chunk exists in the candidate pool."""
    for desired_type in _COMPANION_SECTION_PRIORITY:
        for chunk, _ in ranked_hits:
            md = chunk.metadata or {}
            if (md.get("service_name") or "") != service_name:
                continue
            if (md.get("service_name") or "", md.get("section_title") or "") in primary_keys:
                continue
            if str(md.get("section_type") or "") == desired_type:
                return chunk
    return None


def lookup_flyer_pricing(
    *,
    query: str,
    top_k: int = 3,
    candidate_pool: int = 35,
) -> list[dict[str, Any]]:
    """Embed-search the service-page Chroma store and return up to
    ``top_k`` primary pricing chunks plus one context companion chunk
    per service that surfaced a primary record.

    Two layers of disambiguation, both addressing failure modes the
    main retrieval pipeline already handles but this thin path skips:

    1. **Rerank by preferred service**. Pure embedding similarity
       can't disambiguate platform — "HEK293" queries surface yeast /
       E. coli flyer chunks above mammalian because those flyers have
       higher pricing-text density and embeddings don't encode
       "HEK293 == mammalian". When the query carries a cell-type /
       platform signal we move chunks from the matching service flyer
       to the front of the candidate list before picking primaries.
       See ``_SUBSTRING_HINTS`` / ``_WORD_BOUNDARY_HINTS``. Rerank
       (not filter), so non-preferred services can still fill remaining
       primary slots if the preferred service runs out of pricing
       chunks — same philosophy as the main retriever's biz_line boost.

    2. **Companion chunks**. A primary pricing record alone often
       can't answer quantitative asks. "How much for 100 mg in HEK293"
       needs both the price ($8,000 standard package) AND the yield
       range (200 μg–25 mg/L, avg 3 mg/L) to recognise that 100 mg is
       far above standard-package capacity and needs a scale-up quote.
       For each service that surfaces a primary, we attach one
       same-service companion — preferring yield/benchmark, then
       phase-scale overview, then plan/workflow summary.

    Default ``candidate_pool=35`` (up from 25) because companion
    sections (especially ``benchmark`` yield-range chunks) can rank
    below pricing chunks for "how much" queries: we observed
    "Mammalian Expression Yield Range" landing at rank 25 of 25 for
    a "100 mg HEK293" query, just outside the old pool cap.

    When preferred services are detected, the candidate pool is
    augmented with a metadata-filtered focused search per service —
    this guarantees their pricing chunks have a chance to surface
    even when the unfiltered pool buries them past the cap (observed
    for multi-platform comparison queries like "HEK293 vs CHO vs
    BL21" where the unfiltered top-35 yielded zero pricing chunks
    for either Mammalian or E. coli).
    """
    if not query.strip():
        return []
    try:
        store = get_vectorstore()
        hits = store.similarity_search_with_score(query, k=candidate_pool)
    except Exception:
        return []

    preferred_services = _detect_preferred_services(query)
    ranked_hits = _rerank_by_preferred_service(hits, preferred_services)

    if preferred_services:
        seen_keys: set[tuple[str, str]] = {
            _chunk_dedup_key(chunk) for chunk, _ in ranked_hits
        }
        # Focused pricing hits go to the front of the ranked list:
        # they are already curated to match a preferred service AND
        # be pricing-bearing, so they're strictly stronger candidates
        # for the primary slot than anything the unfiltered pool
        # produced for the same service.
        augmented: list[tuple[Document, float]] = []
        for service_name in preferred_services:
            for hit in _focused_pricing_search(
                store=store, query=query, service_name=service_name,
            ):
                key = _chunk_dedup_key(hit[0])
                if key in seen_keys:
                    continue
                augmented.append(hit)
                seen_keys.add(key)
        ranked_hits = augmented + ranked_hits

    primary_records: list[dict[str, Any]] = []
    primary_keys: set[tuple[str, str]] = set()
    for chunk, _score in ranked_hits:
        if not _is_pricing_chunk(chunk):
            continue
        record = _build_flyer_pricing_record(chunk)
        record["_chunk_role"] = "primary"
        primary_records.append(record)
        md = chunk.metadata or {}
        primary_keys.add(
            (md.get("service_name") or "", md.get("section_title") or "")
        )
        if len(primary_records) >= top_k:
            break

    services_needing_companion: list[str] = []
    seen_services: set[str] = set()
    for record in primary_records:
        sn = record.get("service_name") or ""
        if sn and sn not in seen_services:
            services_needing_companion.append(sn)
            seen_services.add(sn)

    companion_records: list[dict[str, Any]] = []
    for service_name in services_needing_companion:
        chunk = _select_companion_chunk(
            service_name=service_name,
            ranked_hits=ranked_hits,
            primary_keys=primary_keys,
        )
        if chunk is None:
            continue
        record = _build_flyer_pricing_record(chunk)
        record["_chunk_role"] = "companion"
        companion_records.append(record)

    return primary_records + companion_records


__all__ = ["lookup_flyer_pricing"]
