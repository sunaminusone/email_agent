from __future__ import annotations

from src.routing.models import ClarificationOption, ClarificationPayload, DialogueActResult, RoutedObjectState


# Information without which the primary tool cannot execute.
# Products and services have no critical fields — the executor can always attempt a fuzzy search.
_CRITICAL_FIELDS: dict[str, set[str]] = {
    "order":    {"order_number", "customer_identifier"},
    "invoice":  {"invoice_number", "customer_identifier"},
    "shipment": {"order_number", "tracking_number"},
}


def decide_clarification(
    object_routing: RoutedObjectState,
    dialogue_act: DialogueActResult,
    *,
    missing_information: list[str] | None = None,
) -> ClarificationPayload | None:
    # 1. Object disambiguation (highest priority)
    if object_routing.ambiguous_objects:
        ambiguous = object_routing.ambiguous_objects[0]
        options = [
            ClarificationOption(
                label=candidate.display_name or candidate.identifier or candidate.canonical_value,
                value=candidate.display_name or candidate.identifier or candidate.canonical_value,
            )
            for candidate in ambiguous.candidate_refs[:5]
            if candidate.display_name or candidate.identifier or candidate.canonical_value
        ]
        return ClarificationPayload(
            kind="object_disambiguation",
            reason="Clarification is required because object ambiguity remains unresolved.",
            prompt=f"Please clarify which {ambiguous.object_type} you mean.",
            missing_information=[f"{ambiguous.object_type} identity"],
            options=options,
        )

    # 2. Selection without context
    if dialogue_act.act == "selection" and object_routing.primary_object is None:
        return ClarificationPayload(
            kind="selection_context_missing",
            reason="Clarification is required because the selection turn has no active object state to resolve against.",
            prompt="Please specify which prior option you are selecting.",
            missing_information=["selection target"],
        )

    # 3. Ingestion flagged missing critical info
    if missing_information:
        critical = _filter_critical_missing(missing_information, object_routing)
        if critical:
            return ClarificationPayload(
                kind="missing_information",
                reason=f"Clarification is required because critical information is missing: {', '.join(critical)}.",
                prompt=f"Could you please provide the following: {', '.join(critical)}?",
                missing_information=critical,
            )

    return None


def _filter_critical_missing(
    missing_info: list[str],
    object_routing: RoutedObjectState,
) -> list[str]:
    """Only keep missing fields that prevent the primary tool from running."""
    obj_type = _get_primary_object_type(object_routing)
    required = _CRITICAL_FIELDS.get(obj_type, set())
    return [info for info in missing_info if info in required]


def _get_primary_object_type(object_routing: RoutedObjectState) -> str:
    if object_routing.primary_object is not None:
        return object_routing.primary_object.object_type
    if object_routing.active_object is not None:
        return object_routing.active_object.object_type
    return ""
