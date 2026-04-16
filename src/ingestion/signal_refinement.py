from __future__ import annotations

import logging
import re
from typing import Iterable

from src.ingestion.demand_profile import FLAG_DEMAND, INTENT_DEMAND
from src.ingestion.models import (
    AttachmentSignals,
    EntitySpan,
    ParserRequestFlags,
    ParserSignals,
)


_TECHNICAL_FLAG_NAMES = (
    "needs_protocol",
    "needs_troubleshooting",
    "needs_documentation",
    "needs_recommendation",
    "needs_regulatory_info",
)
_COMMERCIAL_FLAG_NAMES = (
    "needs_price",
    "needs_quote",
    "needs_availability",
    "needs_comparison",
    "needs_sample",
    "needs_timeline",
    "needs_customization",
)
_OPERATIONAL_FLAG_NAMES = (
    "needs_order_status",
    "needs_shipping_info",
    "needs_invoice",
    "needs_refund_or_cancellation",
)
# Gap fill: when intent is specific but parser set zero flags in the
# matching family, supplement with a safe default.  Technical family is
# not gap-filled by reconciliation.
_INTENT_DEFAULT_FLAG: dict[str, str] = {
    "pricing_question": "needs_price",
    "timeline_question": "needs_timeline",
    "customization_request": "needs_customization",
    "order_support": "needs_order_status",
    "shipping_question": "needs_shipping_info",
    "complaint": "needs_refund_or_cancellation",
}
_FAMILY_FLAG_NAMES: dict[str, tuple[str, ...]] = {
    "commercial": _COMMERCIAL_FLAG_NAMES,
    "operational": _OPERATIONAL_FLAG_NAMES,
}


logger = logging.getLogger(__name__)


def _has_any_flag(flags: ParserRequestFlags, flag_names: tuple[str, ...]) -> bool:
    return any(getattr(flags, name, False) for name in flag_names)


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
# Entity deduplication and canonicalization
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
# Intent ↔ flag reconciliation (gap fill + cross-family fix)
# ---------------------------------------------------------------------------

def _gap_fill_flags(
    parser_signals: ParserSignals,
) -> ParserSignals:
    """Add a default flag when intent is specific but its family has zero flags.

    Only handles commercial and operational families.  Technical family is
    not gap-filled by reconciliation.
    """
    intent = parser_signals.context.primary_intent
    default_flag = _INTENT_DEFAULT_FLAG.get(intent)
    if default_flag is None:
        return parser_signals

    family = INTENT_DEMAND.get(intent, "general")
    family_flags = _FAMILY_FLAG_NAMES.get(family)
    if family_flags is None:
        return parser_signals

    if _has_any_flag(parser_signals.request_flags, family_flags):
        return parser_signals

    return parser_signals.model_copy(
        update={
            "request_flags": parser_signals.request_flags.model_copy(
                update={default_flag: True}
            )
        }
    )


def _fix_cross_family(
    parser_signals: ParserSignals,
) -> ParserSignals:
    """When intent family is entirely absent from flag families, trust flags.

    Example: intent=pricing_question but only needs_protocol is set.
    The flags are more granular evidence — correct intent to match.
    """
    intent = parser_signals.context.primary_intent
    intent_family = INTENT_DEMAND.get(intent, "general")

    # Vague intents don't constitute a contradiction.
    if intent_family == "general":
        return parser_signals

    active_flag_names = [
        name for name in ParserRequestFlags.model_fields
        if getattr(parser_signals.request_flags, name, False)
    ]
    if not active_flag_names:
        return parser_signals

    flag_families = {
        FLAG_DEMAND.get(f, "general") for f in active_flag_names
    }
    flag_families.discard("general")

    if not flag_families or intent_family in flag_families:
        return parser_signals

    # Intent family is absent from all flag families — trust flags.
    corrected_intent = _dominant_intent_from_flags(
        parser_signals.request_flags,
        "",  # query not needed for flag-based inference
    )
    if corrected_intent is None or corrected_intent == intent:
        return parser_signals

    return parser_signals.model_copy(
        update={
            "context": parser_signals.context.model_copy(
                update={"primary_intent": corrected_intent}
            )
        }
    )


def reconcile_intent_and_flags(
    parser_signals: ParserSignals,
) -> ParserSignals:
    """Final consistency pass: gap fill then cross-family correction."""
    result = _gap_fill_flags(parser_signals)
    result = _fix_cross_family(result)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _active_flag_names(flags: ParserRequestFlags) -> list[str]:
    return [name for name in ParserRequestFlags.model_fields if getattr(flags, name, False)]


def _log_refinement_corrections(
    original: ParserSignals,
    refined: ParserSignals,
) -> None:
    """Log when refinement corrected the parser's output.

    Tracks three categories:
    - intent_changed: parser intent was overridden (validate or cross-family fix)
    - flags_added: flags supplemented by gap fill
    - flags_removed: flags dropped by correction rules
    """
    orig_intent = original.context.primary_intent
    final_intent = refined.context.primary_intent
    orig_flags = set(_active_flag_names(original.request_flags))
    final_flags = set(_active_flag_names(refined.request_flags))

    added = final_flags - orig_flags
    removed = orig_flags - final_flags

    if orig_intent == final_intent and not added and not removed:
        return

    parts: list[str] = []
    if orig_intent != final_intent:
        parts.append(f"intent: {orig_intent} → {final_intent}")
    if added:
        parts.append(f"flags_added: {','.join(sorted(added))}")
    if removed:
        parts.append(f"flags_removed: {','.join(sorted(removed))}")

    logger.warning("parser refinement correction: %s", "; ".join(parts))


def refine_parser_signals(
    parser_signals: ParserSignals,
    *,
    normalized_query: str,
    attachment_signals: AttachmentSignals | None = None,
) -> ParserSignals:
    refined = dedupe_parser_entities(parser_signals)
    refined = canonicalize_parser_entities(refined)
    refined = validate_intent_and_flags(refined, normalized_query)
    refined = reconcile_intent_and_flags(refined)

    _log_refinement_corrections(parser_signals, refined)

    return refined
