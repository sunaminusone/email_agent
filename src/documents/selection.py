from __future__ import annotations

import logging
from typing import Any

from src.documents.storage import generate_presigned_document_url

from .normalization import (
    business_line_matches,
    detect_requested_document_types,
    document_type_matches,
    infer_document_type_from_name,
    normalize_business_line,
    normalize_text,
    tokenize,
)
from .ranking import rank_document_matches
from .retrieval import document_catalog_inventory


logger = logging.getLogger(__name__)


def run_document_selection(
    *,
    query: str,
    catalog_numbers: list[str] | None = None,
    product_names: list[str] | None = None,
    document_names: list[str] | None = None,
    business_line_hint: str = "",
    top_k: int = 5,
) -> dict[str, Any]:
    catalog_numbers = [value.upper() for value in (catalog_numbers or []) if value]
    product_names = product_names or []
    document_names = document_names or []
    inventory = document_catalog_inventory(
        infer_document_type=infer_document_type_from_name,
        normalize_text=normalize_text,
        tokenize=tokenize,
        normalize_business_line=normalize_business_line,
    )
    requested_document_types = detect_requested_document_types(query, document_names)
    normalized_business_line_hint = normalize_business_line(business_line_hint)
    query_tokens = set(
        tokenize(query)
        + [token for number in catalog_numbers for token in tokenize(number)]
        + [token for name in product_names for token in tokenize(name)]
        + [token for name in document_names for token in tokenize(name)]
    )

    matches: list[dict[str, Any]] = []

    for item in inventory:
        score = 0
        strong_match = False
        matched_tokens = sorted(query_tokens.intersection(item["tokens"]))
        score += len(matched_tokens) * 2

        if document_type_matches(item["document_type"], requested_document_types):
            score += 8
            if normalized_business_line_hint and normalized_business_line_hint == item.get("normalized_business_line", ""):
                strong_match = True
        elif requested_document_types:
            score -= 4

        if normalized_business_line_hint and normalized_business_line_hint != "unknown":
            if business_line_matches(normalized_business_line_hint, item.get("normalized_business_line", "")):
                score += 6
            elif item.get("normalized_business_line", ""):
                continue

        if any(name and normalize_text(name) in item["normalized_name"] for name in product_names + document_names):
            score += 6
            strong_match = True

        if score <= 0:
            continue

        if (catalog_numbers or normalized_business_line_hint or product_names) and not strong_match and score < 10:
            continue

        matches.append(
            {
                "file_name": item["file_name"],
                "source_path": item["source_path"],
                "storage_url": item["storage_url"],
                "document_type": item["document_type"],
                "business_line": item.get("business_line", ""),
                "product_scope": item.get("product_scope", ""),
                "catalog_no": item.get("catalog_no", ""),
                "product_name": item.get("product_name", ""),
                "title": item.get("title", ""),
                "score": score,
                "matched_tokens": matched_tokens,
            }
        )

    top_matches = rank_document_matches(matches, top_k=top_k)

    for match in top_matches:
        try:
            match["document_url"] = generate_presigned_document_url(match["storage_url"])
        except Exception as exc:
            logger.warning("Failed to mint presigned URL for %s: %s", match.get("storage_url"), exc)
            match["document_url"] = ""

    return {
        "lookup_mode": "service_documents_pg",
        "requested_document_types": requested_document_types,
        "catalog_numbers": catalog_numbers,
        "business_line_hint": business_line_hint,
        "query_tokens": sorted(query_tokens),
        "documents_found": len(top_matches),
        "matches": top_matches,
    }
