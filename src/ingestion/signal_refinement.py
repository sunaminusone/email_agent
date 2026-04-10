from __future__ import annotations

import re
from typing import Iterable

from src.ingestion.models import AttachmentSignals, EntitySpan, ParserSignals


_DOCUMENT_TERMS = (
    "datasheet",
    "brochure",
    "protocol",
    "manual",
    "coa",
    "sds",
    "technical file",
)
_PRODUCT_INFO_INTRO_PATTERNS = (
    "tell me about",
    "what is",
    "what are",
    "can you tell me about",
)
_TRACKING_TERMS = (
    "tracking",
    "track",
    "where is my order",
    "track my order",
)


def resolve_corrected_intent_values(
    *,
    primary_intent: str,
    intent_confidence: float,
    normalized_query: str,
    needs_invoice: bool = False,
    needs_order_status: bool = False,
    needs_documentation: bool = False,
    needs_price: bool = False,
    needs_quote: bool = False,
    needs_timeline: bool = False,
    needs_customization: bool = False,
    needs_troubleshooting: bool = False,
    needs_availability: bool = False,
    has_order_numbers: bool = False,
) -> tuple[str, float]:
    corrected_intent = primary_intent
    corrected_confidence = intent_confidence or 0.0

    if needs_invoice or needs_order_status or "invoice" in normalized_query or "order" in normalized_query:
        corrected_intent = "order_support"
        corrected_confidence = max(corrected_confidence, 0.85)
    elif needs_documentation:
        corrected_intent = "documentation_request"
        corrected_confidence = max(corrected_confidence, 0.85)
    elif needs_price or needs_quote:
        corrected_intent = "pricing_question"
        corrected_confidence = max(corrected_confidence, 0.85)
    elif needs_timeline:
        corrected_intent = "timeline_question"
        corrected_confidence = max(corrected_confidence, 0.8)
    elif needs_customization:
        corrected_intent = "customization_request"
        corrected_confidence = max(corrected_confidence, 0.8)
    elif needs_troubleshooting:
        corrected_intent = "troubleshooting"
        corrected_confidence = max(corrected_confidence, 0.8)
    elif needs_availability and not has_order_numbers:
        corrected_intent = "product_inquiry"
        corrected_confidence = max(corrected_confidence, 0.75)

    return corrected_intent, corrected_confidence


def _dedupe_entity_spans(values: Iterable[EntitySpan]) -> list[EntitySpan]:
    seen: set[str] = set()
    deduped: list[EntitySpan] = []
    for value in values:
        key = (value.normalized_value or value.text or value.raw or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _canonicalize_spans(
    values: Iterable[EntitySpan],
    canonicalizer,
) -> list[EntitySpan]:
    canonicalized: list[EntitySpan] = []
    for value in values:
        cleaned = str(value.text or value.raw or "").strip()
        if not cleaned:
            continue
        canonical = str(canonicalizer(cleaned) or "").strip() or cleaned
        canonicalized.append(value.model_copy(update={"normalized_value": canonical}))
    return canonicalized


def _preserve_surface_form(values: Iterable[EntitySpan]) -> list[EntitySpan]:
    preserved: list[EntitySpan] = []
    for value in values:
        cleaned = str(value.text or value.raw or "").strip()
        if not cleaned:
            continue
        preserved.append(value.model_copy(update={"normalized_value": cleaned}))
    return preserved


def _normalize_entity_text(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" ,;:")
    return cleaned


def dedupe_parser_entities(parser_signals: ParserSignals) -> ParserSignals:
    entities = parser_signals.entities
    return parser_signals.model_copy(
        update={
            "entities": entities.model_copy(
                update={
                    "product_names": _dedupe_entity_spans(entities.product_names),
                    "catalog_numbers": _dedupe_entity_spans(entities.catalog_numbers),
                    "service_names": _dedupe_entity_spans(entities.service_names),
                    "targets": _dedupe_entity_spans(entities.targets),
                    "species": _dedupe_entity_spans(entities.species),
                    "applications": _dedupe_entity_spans(entities.applications),
                    "order_numbers": _dedupe_entity_spans(entities.order_numbers),
                    "invoice_numbers": _dedupe_entity_spans(entities.invoice_numbers),
                    "document_names": _dedupe_entity_spans(entities.document_names),
                    "company_names": _dedupe_entity_spans(entities.company_names),
                    "customer_names": _dedupe_entity_spans(entities.customer_names),
                }
            ),
            "missing_information": list(dict.fromkeys(parser_signals.missing_information)),
        }
    )


def canonicalize_parser_entities(parser_signals: ParserSignals) -> ParserSignals:
    entities = parser_signals.entities
    return parser_signals.model_copy(
        update={
            "entities": entities.model_copy(
                update={
                    "product_names": _canonicalize_spans(entities.product_names, _normalize_entity_text),
                    "catalog_numbers": _preserve_surface_form(entities.catalog_numbers),
                    "service_names": _canonicalize_spans(entities.service_names, _normalize_entity_text),
                    "targets": _preserve_surface_form(entities.targets),
                    "species": _preserve_surface_form(entities.species),
                    "applications": _preserve_surface_form(entities.applications),
                    "order_numbers": _preserve_surface_form(entities.order_numbers),
                    "invoice_numbers": _preserve_surface_form(entities.invoice_numbers),
                    "document_names": _preserve_surface_form(entities.document_names),
                    "company_names": _preserve_surface_form(entities.company_names),
                    "customer_names": _preserve_surface_form(entities.customer_names),
                }
            )
        }
    )


def correct_intent(parser_signals: ParserSignals, normalized_query: str) -> ParserSignals:
    context = parser_signals.context
    flags = parser_signals.request_flags
    primary_intent, confidence = resolve_corrected_intent_values(
        primary_intent=context.primary_intent,
        intent_confidence=context.intent_confidence or 0.0,
        normalized_query=normalized_query,
        needs_invoice=flags.needs_invoice,
        needs_order_status=flags.needs_order_status,
        needs_documentation=flags.needs_documentation,
        needs_price=flags.needs_price,
        needs_quote=flags.needs_quote,
        needs_timeline=flags.needs_timeline,
        needs_customization=flags.needs_customization,
        needs_troubleshooting=flags.needs_troubleshooting,
        needs_availability=flags.needs_availability,
        has_order_numbers=bool(parser_signals.entities.order_numbers),
    )

    if primary_intent == context.primary_intent and confidence == context.intent_confidence:
        return parser_signals

    return parser_signals.model_copy(
        update={
            "context": context.model_copy(
                update={
                    "primary_intent": primary_intent,
                    "intent_confidence": confidence,
                }
            )
        }
    )


def correct_request_flags(parser_signals: ParserSignals, normalized_query: str) -> ParserSignals:
    updated = parser_signals

    if (
        updated.context.primary_intent == "documentation_request"
        and updated.entities.product_names
        and not updated.entities.catalog_numbers
        and not updated.entities.service_names
        and not any(term in normalized_query for term in _DOCUMENT_TERMS)
        and any(normalized_query.startswith(pattern) for pattern in _PRODUCT_INFO_INTRO_PATTERNS)
    ):
        updated = updated.model_copy(
            update={
                "context": updated.context.model_copy(update={"primary_intent": "product_inquiry"}),
                "request_flags": updated.request_flags.model_copy(
                    update={"needs_documentation": False, "needs_availability": True}
                ),
            }
        )

    if updated.entities.order_numbers and any(term in normalized_query for term in _TRACKING_TERMS):
        updated = updated.model_copy(
            update={
                "request_flags": updated.request_flags.model_copy(
                    update={"needs_shipping_info": True}
                )
            }
        )

    return updated


def apply_attachment_tool_hint_repairs(
    parser_signals: ParserSignals,
    attachment_signals: AttachmentSignals,
) -> ParserSignals:
    if not attachment_signals.has_attachments:
        return parser_signals
    if parser_signals.tool_hints.requires_file_lookup:
        return parser_signals
    if not (
        parser_signals.request_flags.needs_documentation
        or parser_signals.request_flags.needs_protocol
    ):
        return parser_signals
    return parser_signals.model_copy(
        update={
            "tool_hints": parser_signals.tool_hints.model_copy(update={"requires_file_lookup": True})
        }
    )


def refine_parser_signals(
    parser_signals: ParserSignals,
    *,
    normalized_query: str,
    attachment_signals: AttachmentSignals | None = None,
) -> ParserSignals:
    refined = dedupe_parser_entities(parser_signals)
    refined = canonicalize_parser_entities(refined)
    refined = correct_intent(refined, normalized_query)
    refined = correct_request_flags(refined, normalized_query)

    if attachment_signals is not None:
        refined = apply_attachment_tool_hint_repairs(refined, attachment_signals)

    return refined
