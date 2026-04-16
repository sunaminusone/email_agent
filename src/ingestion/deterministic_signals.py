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
_DOCUMENT_TYPE_PATTERNS = {
    "datasheet": ("datasheet", "data sheet"),
    "coa": ("coa",),
    "sds": ("sds",),
    "brochure": ("brochure",),
    "protocol": ("protocol",),
    "manual": ("manual",),
}

_PRODUCT_INTENTS = frozenset({
    "product_inquiry", "pricing_question", "timeline_question",
    "customization_request", "documentation_request", "technical_question",
    "troubleshooting",
})
_OPERATIONAL_INTENTS = frozenset({
    "order_support", "shipping_question", "complaint",
})


def _derive_product_context(parser_signals: ParserSignals | None) -> bool:
    if parser_signals is None:
        return False
    return bool(
        parser_signals.entities.product_names
        or parser_signals.entities.catalog_numbers
        or parser_signals.entities.service_names
        or parser_signals.context.primary_intent in _PRODUCT_INTENTS
    )


def _derive_operational_context(parser_signals: ParserSignals | None) -> bool:
    if parser_signals is None:
        return False
    return bool(
        parser_signals.entities.order_numbers
        or parser_signals.entities.invoice_numbers
        or parser_signals.context.primary_intent in _OPERATIONAL_INTENTS
    )


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


def extract_deterministic_signals(
    query: str,
    parser_signals: ParserSignals | None = None,
) -> DeterministicSignals:
    product_context = _derive_product_context(parser_signals)
    operational_context = _derive_operational_context(parser_signals)

    catalog_numbers, order_numbers, ambiguous_identifiers = _classify_numeric_identifiers(
        query,
        product_context=product_context,
        operational_context=operational_context,
        existing_catalog_numbers=_extract_catalog_numbers(query),
    )

    return DeterministicSignals(
        catalog_numbers=_to_entity_spans(catalog_numbers),
        order_numbers=_to_entity_spans(order_numbers),
        invoice_numbers=_to_entity_spans(_extract_invoice_numbers(query)),
        ambiguous_identifiers=_to_value_signals(ambiguous_identifiers),
        document_types=_to_value_signals(_extract_document_types(query)),
    )
