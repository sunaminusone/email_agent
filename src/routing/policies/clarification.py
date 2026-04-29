from __future__ import annotations

from src.routing.models import ClarificationOption, ClarificationPayload, DialogueActResult, RoutedObjectState


_CRITICAL_FIELDS: dict[str, set[str]] = {
    "order": {"order_number", "customer_identifier", "customer_name"},
    "invoice": {"invoice_number", "customer_identifier", "customer_name"},
    "shipment": {"order_number", "tracking_number", "customer_identifier", "customer_name"},
}


def decide_clarification(
    object_routing: RoutedObjectState,
    dialogue_act: DialogueActResult,
    *,
    missing_information: list[str] | None = None,
    missing_object_type: str = "",
) -> ClarificationPayload | None:
    """Routing-layer clarification: object ambiguity and selection context only.

    Parameter-missing clarification has moved to path evaluation (tool readiness).
    """
    # 1. Object disambiguation
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
    if (
        dialogue_act.act == "selection"
        and object_routing.primary_object is None
        and object_routing.active_object is None
    ):
        return ClarificationPayload(
            kind="selection_context_missing",
            reason="Clarification is required because the selection turn has no active object state to resolve against.",
            prompt="Please specify which prior option you are selecting.",
            missing_information=["selection target"],
        )

    critical_missing = _filter_critical_missing(
        missing_information or [],
        object_routing=object_routing,
        missing_object_type=missing_object_type,
    )
    if critical_missing:
        return ClarificationPayload(
            kind="missing_information",
            reason="Clarification is required because critical operational identifiers are missing.",
            prompt="Please provide the missing identifiers so the request can be looked up safely.",
            missing_information=critical_missing,
        )

    return None


def _filter_critical_missing(
    missing_information: list[str],
    *,
    object_routing: RoutedObjectState,
    missing_object_type: str = "",
) -> list[str]:
    object_type = (
        missing_object_type
        or (object_routing.primary_object.object_type if object_routing.primary_object is not None else "")
        or (object_routing.active_object.object_type if object_routing.active_object is not None else "")
    )
    required = _CRITICAL_FIELDS.get(object_type, set())
    return [item for item in missing_information if item in required]
