from __future__ import annotations

import re
from typing import Iterable

from src.ingestion.models import AttachmentSignals, EntitySpan, ParserRequestFlags, ParserSignals


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
_TECHNICAL_WORKFLOW_TERMS = (
    "workflow",
    "process",
    "how does",
    "how do",
    "development",
    "phases",
    "steps",
    "mechanism",
    "validation",
    "assay",
    "protocol",
)
_TROUBLESHOOTING_TERMS = (
    "troubleshoot",
    "not working",
    "issue",
    "problem",
    "low expression",
    "poor yield",
    "failed",
    "optimize",
    "optimization",
)


# ---------------------------------------------------------------------------
# Intent validation (v3): non-destructive
# ---------------------------------------------------------------------------

def validate_intent_and_flags(
    parser_signals: ParserSignals,
    normalized_query: str,
) -> ParserSignals:
    """Validate primary_intent against request_flags. Non-destructive.

    Only corrects when primary_intent is too vague ('unknown', 'general_info')
    and a dominant intent can be inferred from request_flags. Does NOT overwrite
    a specific intent the parser already classified — multi-intent information
    in request_flags is preserved untouched.
    """
    context = parser_signals.context
    flags = parser_signals.request_flags
    primary_intent = context.primary_intent
    confidence = context.intent_confidence or 0.0

    dominant_intent = _dominant_intent_from_flags(flags, normalized_query)
    if dominant_intent and primary_intent in {"unknown", "general_info"}:
        primary_intent = dominant_intent
        confidence = max(confidence, 0.80)

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


def _dominant_intent_from_flags(flags: ParserRequestFlags, query: str) -> str | None:
    """Pick the most specific intent from flags. Used only when primary_intent
    is too vague. Does NOT override a specific parser classification."""
    flag_intent_map = [
        (flags.needs_invoice or flags.needs_order_status, "order_support"),
        (flags.needs_shipping_info, "shipping_question"),
        (flags.needs_documentation, "documentation_request"),
        (flags.needs_price or flags.needs_quote, "pricing_question"),
        (flags.needs_timeline, "timeline_question"),
        (flags.needs_customization, "customization_request"),
        (flags.needs_troubleshooting, "troubleshooting"),
        (flags.needs_protocol, "technical_question"),
    ]
    for is_active, intent in flag_intent_map:
        if is_active:
            return intent
    return None


# ---------------------------------------------------------------------------
# Entity deduplication and canonicalization (unchanged)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Request flag correction (unchanged)
# ---------------------------------------------------------------------------

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

    # Technical question fallback: if the LLM classified as technical_question
    # or troubleshooting but didn't set any technical flag, infer from query terms.
    updated = _ensure_technical_flags(updated, normalized_query)

    return updated


def _ensure_technical_flags(parser_signals: ParserSignals, normalized_query: str) -> ParserSignals:
    """Ensure technical-intent queries have at least one matching request flag."""
    intent = parser_signals.context.primary_intent
    flags = parser_signals.request_flags

    if intent not in ("technical_question", "troubleshooting"):
        return parser_signals

    technical_flags = (
        flags.needs_protocol
        or flags.needs_troubleshooting
        or flags.needs_documentation
        or flags.needs_recommendation
        or flags.needs_regulatory_info
    )
    if technical_flags:
        return parser_signals

    flag_updates: dict[str, bool] = {}

    if intent == "troubleshooting" or any(term in normalized_query for term in _TROUBLESHOOTING_TERMS):
        flag_updates["needs_troubleshooting"] = True

    if any(term in normalized_query for term in _TECHNICAL_WORKFLOW_TERMS):
        flag_updates["needs_protocol"] = True

    # Fallback: if intent is technical_question but no specific term matched,
    # default to needs_protocol to route to the RAG tool.
    if not flag_updates and intent == "technical_question":
        flag_updates["needs_protocol"] = True

    if flag_updates:
        return parser_signals.model_copy(
            update={
                "request_flags": flags.model_copy(update=flag_updates),
            }
        )

    return parser_signals


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refine_parser_signals(
    parser_signals: ParserSignals,
    *,
    normalized_query: str,
    attachment_signals: AttachmentSignals | None = None,
) -> ParserSignals:
    refined = dedupe_parser_entities(parser_signals)
    refined = canonicalize_parser_entities(refined)
    refined = validate_intent_and_flags(refined, normalized_query)
    refined = correct_request_flags(refined, normalized_query)
    return refined
