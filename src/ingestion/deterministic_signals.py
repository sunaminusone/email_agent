from __future__ import annotations

import re

from src.ingestion.models import DeterministicSignals, EntitySpan, ParserSignals, SourceAttribution, ValueSignal


_CATALOG_HINT_PATTERN = re.compile(
    r"\b(?:product|catalog|cat(?:alog)?(?:\s*(?:no|number|#))?|sku|item|id|identifier)\s*[:#-]?\s*((?:PM-CAR\d{4})|(?:PM-LNP-\d{4})|(?:\d{5})|(?:[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+))\b",
    re.IGNORECASE,
)
_HIGH_CONFIDENCE_CATALOG_PATTERNS = (
    re.compile(r"\bPM-CAR\d{4}\b", re.IGNORECASE),
    re.compile(r"\bPM-LNP-\d{4}\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b"),
)
_NUMERIC_IDENTIFIER_PATTERN = re.compile(r"\b\d{4,6}\b")
_INVOICE_HINT_PATTERN = re.compile(
    r"\b(?:invoice|inv|bill|billing)\s*[:#-]?\s*([A-Za-z0-9-]{4,})\b",
    re.IGNORECASE,
)
_IDENTIFIER_MISSING_HINTS = (
    "product name",
    "catalog number",
    "catalog no",
    "identifier",
    "product identifier",
    "alias",
    "target",
)
_PRODUCT_CONTEXT_TERMS = (
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
_SERVICE_CONTEXT_TERMS = (
    "service",
    "services",
    "assay",
    "screening",
    "testing",
    "sequencing",
    "analysis",
)
_INVOICE_CONTEXT_TERMS = (
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
_ORDER_CONTEXT_TERMS = (
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
_DOCUMENTATION_CONTEXT_TERMS = (
    "datasheet",
    "data sheet",
    "coa",
    "sds",
    "brochure",
    "protocol",
    "manual",
)
_PRICING_CONTEXT_TERMS = (
    "quote",
    "quotation",
    "price",
    "pricing",
    "cost",
)
_TIMELINE_CONTEXT_TERMS = (
    "lead time",
    "eta",
    "turnaround",
    "how long",
    "delivery time",
)
_TECHNICAL_CONTEXT_TERMS = (
    "technical",
    "protocol",
    "workflow",
    "development",
    "mechanism",
    "validation",
    "assay",
    "supported models",
    "model support",
    "elisa",
    "western blot",
    "wb",
    "ihc",
    "immunohistochemistry",
    "flow cytometry",
    "facs",
    "pcr",
)
_DOCUMENT_TYPE_PATTERNS = {
    "datasheet": ("datasheet", "data sheet"),
    "coa": ("coa",),
    "sds": ("sds",),
    "brochure": ("brochure",),
    "protocol": ("protocol",),
    "manual": ("manual",),
}


def _signal_attribution() -> SourceAttribution:
    return SourceAttribution(
        source_type="deterministic",
        recency="CURRENT_TURN",
        confidence=1.0,
        source_label="ingestion.deterministic",
    )


def _to_entity_spans(values: list[str]) -> list[EntitySpan]:
    attribution = _signal_attribution()
    spans: list[EntitySpan] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        spans.append(
            EntitySpan(
                text=cleaned,
                raw=cleaned,
                normalized_value=cleaned,
                attribution=attribution,
            )
        )
    return spans


def _to_value_signals(values: list[str]) -> list[ValueSignal]:
    attribution = _signal_attribution()
    signals: list[ValueSignal] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        signals.append(
            ValueSignal(
                value=cleaned,
                raw=cleaned,
                normalized_value=cleaned,
                attribution=attribution,
            )
        )
    return signals


def _extract_invoice_numbers(query: str) -> list[str]:
    seen: set[str] = set()
    invoice_numbers: list[str] = []
    for match in _INVOICE_HINT_PATTERN.finditer(query):
        candidate = match.group(1).strip().upper()
        if candidate in seen:
            continue
        seen.add(candidate)
        invoice_numbers.append(candidate)
    return invoice_numbers


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
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


def _contains_context_term(query: str, terms: tuple[str, ...]) -> bool:
    normalized = str(query or "").strip().lower()
    return any(term in normalized for term in terms)


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


def _extract_catalog_numbers(query: str) -> list[str]:
    normalized_query = str(query or "").strip()
    direct_catalog_matches = [match.group(1).strip().upper() for match in _CATALOG_HINT_PATTERN.finditer(normalized_query)]

    high_confidence_catalog_matches: list[str] = []
    for pattern in _HIGH_CONFIDENCE_CATALOG_PATTERNS:
        high_confidence_catalog_matches.extend(match.group(0).strip().upper() for match in pattern.finditer(normalized_query))

    return _dedupe_preserve_order([*direct_catalog_matches, *high_confidence_catalog_matches])


def _classify_numeric_identifiers(
    query: str,
    *,
    product_context: bool,
    operational_context: bool,
    existing_catalog_numbers: list[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    catalog_numbers: list[str] = list(existing_catalog_numbers or [])
    order_numbers: list[str] = []
    ambiguous_identifiers: list[str] = []

    for match in _NUMERIC_IDENTIFIER_PATTERN.finditer(str(query or "").strip()):
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

    return (
        _dedupe_preserve_order(catalog_numbers),
        _dedupe_preserve_order(order_numbers),
        _dedupe_preserve_order(ambiguous_identifiers),
    )


def _extract_document_types(query: str) -> list[str]:
    normalized = str(query or "").strip().lower()
    detected: list[str] = []
    for document_type, patterns in _DOCUMENT_TYPE_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            detected.append(document_type)
    return detected


def detect_document_types(query: str) -> list[str]:
    return _extract_document_types(query)


def strip_identifier_missing_information(missing_information: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in missing_information:
        normalized = str(item or "").strip().lower()
        if normalized and any(hint in normalized for hint in _IDENTIFIER_MISSING_HINTS):
            continue
        cleaned.append(item)
    return cleaned


def classify_identifier_candidates(query: str) -> dict[str, object]:
    signals = extract_deterministic_signals(query)
    return {
        "catalog_numbers": [span.text for span in signals.catalog_numbers],
        "order_numbers": [span.text for span in signals.order_numbers],
        "ambiguous_identifiers": [signal.value for signal in signals.ambiguous_identifiers],
        "product_context": signals.product_context,
        "invoice_context": signals.invoice_context,
        "order_context": signals.order_context,
        "documentation_context": signals.documentation_context,
        "pricing_context": signals.pricing_context,
        "timeline_context": signals.timeline_context,
    }


def extract_deterministic_signals(
    query: str,
    parser_signals: ParserSignals | None = None,
) -> DeterministicSignals:
    invoice_numbers = _extract_invoice_numbers(query)
    document_types = _extract_document_types(query)

    documentation_context = _contains_context_term(query, _DOCUMENTATION_CONTEXT_TERMS) or bool(document_types)
    pricing_context = _contains_context_term(query, _PRICING_CONTEXT_TERMS)
    timeline_context = _contains_context_term(query, _TIMELINE_CONTEXT_TERMS)
    technical_context = _contains_context_term(query, _TECHNICAL_CONTEXT_TERMS)
    product_context = (
        _contains_context_term(query, _PRODUCT_CONTEXT_TERMS)
        or _looks_like_product_reference(query)
        or documentation_context
        or pricing_context
        or timeline_context
        or technical_context
    )
    invoice_context = (
        _contains_context_term(query, _INVOICE_CONTEXT_TERMS)
        or _looks_like_invoice_reference(query)
        or bool(invoice_numbers)
    )
    order_context = _contains_context_term(query, _ORDER_CONTEXT_TERMS) or _looks_like_order_reference(query)
    operational_context = invoice_context or order_context

    catalog_numbers, order_numbers, ambiguous_identifiers = _classify_numeric_identifiers(
        query,
        product_context=product_context,
        operational_context=operational_context,
        existing_catalog_numbers=_extract_catalog_numbers(query),
    )

    service_context = _contains_context_term(query, _SERVICE_CONTEXT_TERMS) or bool(
        parser_signals and parser_signals.entities.service_names
    )

    return DeterministicSignals(
        catalog_numbers=_to_entity_spans(catalog_numbers),
        order_numbers=_to_entity_spans(order_numbers),
        invoice_numbers=_to_entity_spans(invoice_numbers),
        ambiguous_identifiers=_to_value_signals(ambiguous_identifiers),
        document_types=_to_value_signals(document_types),
        product_context=product_context,
        service_context=service_context,
        invoice_context=invoice_context,
        order_context=order_context,
        documentation_context=documentation_context,
        pricing_context=pricing_context,
        timeline_context=timeline_context,
        technical_context=technical_context,
    )
