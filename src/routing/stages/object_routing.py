from __future__ import annotations

from src.objects.models import ResolvedObjectState
from src.routing.models import ExecutionAmbiguity, ExecutionObjectRef, RoutedObjectState


def resolve_object_routing(resolved_object_state: ResolvedObjectState) -> RoutedObjectState:
    if resolved_object_state.ambiguous_sets:
        return RoutedObjectState(
            primary_object=None,
            active_object=_to_execution_object_ref(resolved_object_state.active_object),
            secondary_objects=[
                object_ref
                for candidate in resolved_object_state.secondary_objects
                if (object_ref := _to_execution_object_ref(candidate)) is not None
            ],
            ambiguous_objects=[_to_execution_ambiguity(item) for item in resolved_object_state.ambiguous_sets],
            routing_status="ambiguous",
            should_block_execution=True,
            reason=resolved_object_state.resolution_reason or "Routing blocked because object ambiguity remains unresolved.",
        )

    primary_object = _to_execution_object_ref(resolved_object_state.primary_object)
    active_object = _to_execution_object_ref(resolved_object_state.active_object)
    routing_status = _routing_status(resolved_object_state)
    should_block_execution = primary_object is None and active_object is None

    return RoutedObjectState(
        primary_object=primary_object,
        active_object=active_object,
        secondary_objects=[
            object_ref
            for candidate in resolved_object_state.secondary_objects
            if (object_ref := _to_execution_object_ref(candidate)) is not None
        ],
        ambiguous_objects=[],
        routing_status=routing_status,
        should_block_execution=should_block_execution,
        reason=resolved_object_state.resolution_reason or _default_reason(routing_status),
    )


def _routing_status(resolved_object_state: ResolvedObjectState) -> str:
    if resolved_object_state.primary_object is not None:
        if resolved_object_state.used_memory_context:
            return "contextual_reuse"
        return "resolved"
    if resolved_object_state.active_object is not None:
        return "contextual_reuse"
    return "unresolved"


def _default_reason(routing_status: str) -> str:
    if routing_status == "resolved":
        return "Routing selected a resolved primary object for execution."
    if routing_status == "contextual_reuse":
        return "Routing reused contextual object state for the current turn."
    return "Routing could not determine an execution-ready object."


def _to_execution_object_ref(candidate) -> ExecutionObjectRef | None:
    if candidate is None:
        return None
    return ExecutionObjectRef(
        object_type=candidate.object_type,
        canonical_value=candidate.canonical_value,
        display_name=candidate.display_name,
        identifier=candidate.identifier,
        identifier_type=candidate.identifier_type,
        business_line=candidate.business_line,
    )


def _to_execution_ambiguity(ambiguous_set) -> ExecutionAmbiguity:
    candidate_refs = []
    for candidate in ambiguous_set.candidates:
        candidate_ref = _to_execution_object_ref(candidate)
        if candidate_ref is not None:
            candidate_refs.append(candidate_ref)
    return ExecutionAmbiguity(
        object_type=ambiguous_set.object_type,
        query_value=ambiguous_set.query_value,
        candidate_refs=candidate_refs,
        ambiguity_kind=ambiguous_set.ambiguity_kind,
        clarification_focus=ambiguous_set.clarification_focus,
        suggested_disambiguation_fields=ambiguous_set.suggested_disambiguation_fields,
        reason=ambiguous_set.reason,
    )
