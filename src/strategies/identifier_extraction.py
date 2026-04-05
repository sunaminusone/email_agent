from __future__ import annotations

import re
from typing import Any


CATALOG_HINT_PATTERN = re.compile(
    r"\b(?:product|catalog|cat(?:alog)?(?:\s*(?:no|number|#))?|sku|item|id|identifier)\s*[:#-]?\s*((?:PM-CAR\d{4})|(?:PM-LNP-\d{4})|(?:\d{5})|(?:[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+))\b",
    re.IGNORECASE,
)
HIGH_CONFIDENCE_CATALOG_PATTERNS = [
    re.compile(r"\bPM-CAR\d{4}\b", re.IGNORECASE),
    re.compile(r"\bPM-LNP-\d{4}\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b", re.IGNORECASE),
]
NUMERIC_IDENTIFIER_PATTERN = re.compile(r"\b\d{4,6}\b")

IDENTIFIER_MISSING_HINTS = (
    "product name",
    "catalog number",
    "catalog no",
    "identifier",
    "product identifier",
    "alias",
    "target",
)

PRODUCT_CONTEXT_TERMS = (
    "product",
    "products",
    "catalog",
    "catalog #",
    "catalog no",
    "catalog number",
    "cat no",
    "cat#",
    "cat #",
    "item",
    "sku",
    "antigen",
    "clone",
    "isotype",
    "datasheet",
    "data sheet",
    "coa",
    "sds",
    "brochure",
    "antibody",
    "antibodies",
    "reagent",
    "pm-car",
    "pm-lnp",
)
INVOICE_CONTEXT_TERMS = (
    "invoice",
    "invoices",
    "billing",
    "bill",
    "payment",
    "remit",
    "remittance",
    "amount due",
    "balance due",
    "invoice status",
    "invoice amount",
    "status of invoice",
    "invoice balance",
    "invoice due",
)
ORDER_CONTEXT_TERMS = (
    "order",
    "orders",
    "po",
    "purchase order",
    "order status",
    "status of order",
    "sales order",
    "so ",
    "tracking",
    "shipment",
    "shipping",
    "delivery",
)
DOCUMENTATION_CONTEXT_TERMS = (
    "datasheet",
    "data sheet",
    "coa",
    "sds",
    "brochure",
    "protocol",
    "manual",
)
TECHNICAL_CONTEXT_TERMS = (
    "technical",
    "protocol",
    "validation",
    "assay",
    "elisa",
    "western blot",
    "wb",
    "ihc",
    "immunohistochemistry",
    "flow cytometry",
    "facs",
    "pcr",
)
PRICING_CONTEXT_TERMS = (
    "quote",
    "quotation",
    "price",
    "pricing",
    "cost",
)
TIMELINE_CONTEXT_TERMS = (
    "lead time",
    "eta",
    "turnaround",
    "how long",
    "delivery time",
)
DOCUMENT_TYPE_PATTERNS = {
    "datasheet": ("datasheet", "data sheet"),
    "coa": ("coa",),
    "sds": ("sds",),
    "brochure": ("brochure",),
    "protocol": ("protocol",),
    "manual": ("manual",),
}


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def _contains_context_terms(query: str, terms: tuple[str, ...]) -> bool:
    normalized_query = str(query or "").strip().lower()
    return any(term in normalized_query for term in terms)


def _looks_like_product_reference(query: str) -> bool:
    normalized_query = str(query or "").strip().lower()
    product_reference_patterns = [
        r"\b(?:product|antibody|catalog|cat(?:alog)?(?:\s*(?:no|number|#))?|item|sku)\s+[a-z0-9-]+\b",
        r"\b(?:datasheet|data sheet|brochure|coa|sds|quote|price|availability|lead time)\s+(?:for\s+)?[a-z0-9-]+\b",
    ]
    return any(re.search(pattern, normalized_query) for pattern in product_reference_patterns)


def _looks_like_invoice_reference(query: str) -> bool:
    normalized_query = str(query or "").strip().lower()
    invoice_reference_patterns = [
        r"\b(?:invoice|bill|billing)\s+[a-z0-9-]+\b",
        r"\bstatus of invoice\s+[a-z0-9-]+\b",
        r"\binvoice\s+#?\s*[a-z0-9-]+\b",
    ]
    return any(re.search(pattern, normalized_query) for pattern in invoice_reference_patterns)


def _looks_like_order_reference(query: str) -> bool:
    normalized_query = str(query or "").strip().lower()
    order_reference_patterns = [
        r"\b(?:order|po|purchase order|shipment|tracking)\s+[a-z0-9-]+\b",
        r"\bstatus of order\s+[a-z0-9-]+\b",
    ]
    return any(re.search(pattern, normalized_query) for pattern in order_reference_patterns)


def classify_identifier_candidates(query: str) -> dict[str, Any]:
    normalized_query = str(query or "").strip()
    direct_catalog_matches = [match.group(1).strip().upper() for match in CATALOG_HINT_PATTERN.finditer(normalized_query)]

    high_confidence_catalog_matches: list[str] = []
    for pattern in HIGH_CONFIDENCE_CATALOG_PATTERNS:
        high_confidence_catalog_matches.extend(match.group(0).strip().upper() for match in pattern.finditer(normalized_query))

    documentation_context = _contains_context_terms(normalized_query, DOCUMENTATION_CONTEXT_TERMS)
    pricing_context = _contains_context_terms(normalized_query, PRICING_CONTEXT_TERMS)
    timeline_context = _contains_context_terms(normalized_query, TIMELINE_CONTEXT_TERMS)
    technical_context = _contains_context_terms(normalized_query, TECHNICAL_CONTEXT_TERMS)

    product_context = (
        _contains_context_terms(normalized_query, PRODUCT_CONTEXT_TERMS)
        or _looks_like_product_reference(normalized_query)
        or documentation_context
        or pricing_context
        or timeline_context
        or technical_context
    )
    invoice_context = _contains_context_terms(normalized_query, INVOICE_CONTEXT_TERMS) or _looks_like_invoice_reference(normalized_query)
    order_context = _contains_context_terms(normalized_query, ORDER_CONTEXT_TERMS) or _looks_like_order_reference(normalized_query)
    operational_context = invoice_context or order_context

    catalog_numbers = _dedupe_preserve_order([*direct_catalog_matches, *high_confidence_catalog_matches])
    order_numbers: list[str] = []
    ambiguous_identifiers: list[str] = []

    for match in NUMERIC_IDENTIFIER_PATTERN.finditer(normalized_query):
        candidate = match.group(0).strip().upper()
        if candidate in catalog_numbers:
            continue
        if product_context and not operational_context:
            catalog_numbers.append(candidate)
            continue
        if operational_context and not product_context:
            order_numbers.append(candidate)
            continue
        ambiguous_identifiers.append(candidate)

    return {
        "catalog_numbers": _dedupe_preserve_order(catalog_numbers),
        "order_numbers": _dedupe_preserve_order(order_numbers),
        "ambiguous_identifiers": _dedupe_preserve_order(ambiguous_identifiers),
        "product_context": product_context,
        "invoice_context": invoice_context,
        "order_context": order_context,
        "documentation_context": documentation_context,
        "pricing_context": pricing_context,
        "timeline_context": timeline_context,
    }


def strip_identifier_missing_information(missing_information: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in missing_information:
        normalized = str(item or "").strip().lower()
        if normalized and any(hint in normalized for hint in IDENTIFIER_MISSING_HINTS):
            continue
        cleaned.append(item)
    return cleaned


def detect_document_types(query: str) -> list[str]:
    normalized = str(query or "").strip().lower()
    detected: list[str] = []
    for document_type, patterns in DOCUMENT_TYPE_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            detected.append(document_type)
    return detected
