from __future__ import annotations

from src.routing.models import ClarificationOption, ClarificationPayload, DialogueActResult, RoutedObjectState


def decide_clarification(
    object_routing: RoutedObjectState,
    dialogue_act: DialogueActResult,
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
    if dialogue_act.act == "selection" and object_routing.primary_object is None:
        return ClarificationPayload(
            kind="selection_context_missing",
            reason="Clarification is required because the selection turn has no active object state to resolve against.",
            prompt="Please specify which prior option you are selecting.",
            missing_information=["selection target"],
        )

    return None
