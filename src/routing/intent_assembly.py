"""Deterministic intent group assembly.

Runs AFTER object resolution. Binds request_flags to resolved objects
using flag-to-object-type affinity rules derived from tool capabilities.

Usage:
    from src.routing.intent_assembly import assemble_intent_groups

    groups = assemble_intent_groups(
        request_flags=ingestion_bundle.turn_signals.parser_signals.request_flags,
        resolved_objects=[resolved_object_state.primary_object, *resolved_object_state.secondary_objects],
        semantic_intent=ingestion_bundle.turn_signals.parser_signals.context.semantic_intent,
    )
"""
from __future__ import annotations

from src.common.models import IntentGroup
from src.ingestion.models import ParserRequestFlags


# ---------------------------------------------------------------------------
# Flag → object_type affinity
# Derived from ToolCapability.supported_request_flags + supported_object_types.
# Can also be computed at startup via build_flag_object_affinity().
# ---------------------------------------------------------------------------

_FLAG_OBJECT_AFFINITY: dict[str, set[str]] = {
    "needs_order_status":           {"order"},
    "needs_shipping_info":          {"shipment", "order"},
    "needs_invoice":                {"invoice", "order", "customer"},
    "needs_price":                  {"product", "service"},
    "needs_quote":                  {"product", "service"},
    "needs_availability":           {"product", "service"},
    "needs_comparison":             {"product", "service"},
    "needs_sample":                 {"product", "service"},
    "needs_protocol":               {"product", "service", "scientific_target"},
    "needs_troubleshooting":        {"product", "service"},
    "needs_documentation":          {"product", "service", "document"},
    "needs_customization":          {"product", "service"},
    "needs_timeline":               {"product", "service", "order"},
    "needs_recommendation":         {"product", "service", "scientific_target"},
    "needs_regulatory_info":        {"product", "service"},
    "needs_refund_or_cancellation": {"order", "invoice"},
}

# Flag → intent classification (for per-group intent labeling)
_FLAG_INTENT: dict[str, str] = {
    "needs_order_status":           "order_support",
    "needs_shipping_info":          "shipping_question",
    "needs_invoice":                "order_support",
    "needs_price":                  "pricing_question",
    "needs_quote":                  "pricing_question",
    "needs_availability":           "product_inquiry",
    "needs_comparison":             "product_inquiry",
    "needs_sample":                 "product_inquiry",
    "needs_protocol":               "technical_question",
    "needs_troubleshooting":        "troubleshooting",
    "needs_documentation":          "documentation_request",
    "needs_customization":          "customization_request",
    "needs_timeline":               "timeline_question",
    "needs_recommendation":         "technical_question",
    "needs_regulatory_info":        "technical_question",
    "needs_refund_or_cancellation": "order_support",
}

# ---------------------------------------------------------------------------
# Startup validation: mappings must cover every flag in ParserRequestFlags
# ---------------------------------------------------------------------------
_ALL_FLAGS = set(ParserRequestFlags.model_fields)
assert set(_FLAG_OBJECT_AFFINITY) == _ALL_FLAGS, (
    f"_FLAG_OBJECT_AFFINITY keys mismatch ParserRequestFlags: "
    f"missing={_ALL_FLAGS - set(_FLAG_OBJECT_AFFINITY)}, "
    f"extra={set(_FLAG_OBJECT_AFFINITY) - _ALL_FLAGS}"
)
assert set(_FLAG_INTENT) == _ALL_FLAGS, (
    f"_FLAG_INTENT keys mismatch ParserRequestFlags: "
    f"missing={_ALL_FLAGS - set(_FLAG_INTENT)}, "
    f"extra={set(_FLAG_INTENT) - _ALL_FLAGS}"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_intent_groups(
    request_flags: ParserRequestFlags,
    resolved_objects: list,
    semantic_intent: str = "unknown",
) -> list[IntentGroup]:
    """Deterministically bind active request_flags to resolved objects.

    Args:
        request_flags: flat boolean flags from ingestion parser.
        resolved_objects: list of ObjectCandidate (or any object with
            object_type, identifier, display_name attributes).
        semantic_intent: fallback intent from parser context.

    Returns:
        List of IntentGroup, one per resolved-object (or one unbound group
        if flags don't match any object).
    """
    objects = [obj for obj in resolved_objects if obj is not None]
    active_flags = _get_active_flags(request_flags)

    if not active_flags:
        return _single_group_from_intent(semantic_intent, objects)

    # Step 1: For each flag, find objects whose type matches the flag's affinity
    flag_bindings: dict[str, list] = {}
    for flag in active_flags:
        affinity = _FLAG_OBJECT_AFFINITY.get(flag, set())
        matched = [obj for obj in objects if getattr(obj, "object_type", "") in affinity]
        flag_bindings[flag] = matched

    # Step 2: Group flags by their matched object
    object_groups: dict[str, list[str]] = {}   # object key → [flag_names]
    unbound_flags: list[str] = []

    for flag, matched_objects in flag_bindings.items():
        if not matched_objects:
            unbound_flags.append(flag)
        else:
            for obj in matched_objects:
                key = _object_key(obj)
                object_groups.setdefault(key, []).append(flag)

    # Step 3: Build IntentGroup per object
    groups: list[IntentGroup] = []
    for obj_key, flags in object_groups.items():
        obj = _find_object_by_key(obj_key, objects)
        deduped_flags = list(dict.fromkeys(flags))
        groups.append(IntentGroup(
            intent=_infer_group_intent(deduped_flags, semantic_intent),
            request_flags=deduped_flags,
            object_type=getattr(obj, "object_type", "") if obj else "",
            object_identifier=getattr(obj, "identifier", "") if obj else "",
            object_display_name=getattr(obj, "display_name", "") if obj else "",
            confidence=0.85,
        ))

    # Step 4: Unbound flags → general group (no specific object)
    if unbound_flags:
        groups.append(IntentGroup(
            intent=_infer_group_intent(unbound_flags, semantic_intent),
            request_flags=list(dict.fromkeys(unbound_flags)),
            confidence=0.60,
        ))

    return groups or _single_group_from_intent(semantic_intent, objects)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active_flags(request_flags: ParserRequestFlags) -> list[str]:
    return [
        field_name
        for field_name in ParserRequestFlags.model_fields
        if getattr(request_flags, field_name, False)
    ]


def _object_key(obj) -> str:
    identifier = getattr(obj, "identifier", "") or ""
    display_name = getattr(obj, "display_name", "") or ""
    object_type = getattr(obj, "object_type", "") or ""
    return identifier or display_name or object_type


def _find_object_by_key(key: str, objects: list):
    for obj in objects:
        if _object_key(obj) == key:
            return obj
    return None


def _infer_group_intent(flags: list[str], fallback_intent: str) -> str:
    """Pick the most specific intent from a set of flags."""
    for flag in flags:
        intent = _FLAG_INTENT.get(flag)
        if intent:
            return intent
    return fallback_intent


def _single_group_from_intent(semantic_intent: str, objects: list) -> list[IntentGroup]:
    """Fallback: no active flags → one group from semantic_intent."""
    if not objects:
        return [IntentGroup(intent=semantic_intent, confidence=0.50)]
    primary = objects[0]
    return [IntentGroup(
        intent=semantic_intent,
        object_type=getattr(primary, "object_type", ""),
        object_identifier=getattr(primary, "identifier", ""),
        object_display_name=getattr(primary, "display_name", ""),
        confidence=0.50,
    )]
