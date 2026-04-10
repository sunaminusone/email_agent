from __future__ import annotations

from src.routing.models import ExecutionIntent, RoutingDecision, RoutingInput
from src.routing.policies import build_result_assembly_policy, decide_clarification, decide_handoff
from src.routing.stages import resolve_dialogue_act, resolve_modality, resolve_object_routing, select_tools


def route(routing_input: RoutingInput) -> RoutingDecision:
    object_routing = resolve_object_routing(routing_input.resolved_object_state)
    dialogue_act = resolve_dialogue_act(routing_input.query, object_routing)
    modality_decision = resolve_modality(routing_input.query, object_routing, dialogue_act)

    # These are internal routing controls, not public routing contracts.
    clarification = decide_clarification(object_routing, dialogue_act)
    needs_clarification = clarification is not None
    handoff_required, handoff_reason = decide_handoff(
        risk_level=routing_input.risk_level,
        needs_human_review=routing_input.needs_human_review,
    )
    selected_tools, tool_selection_reason = (
        select_tools(routing_input.query, object_routing, dialogue_act, modality_decision)
        if not needs_clarification and not handoff_required
        else ([], "Tool execution is deferred because clarification or handoff takes priority.")
    )
    assembly_policy_reason = build_result_assembly_policy(modality_decision, selected_tools)
    execution_intent = _build_execution_intent(
        query=routing_input.query,
        object_routing=object_routing,
        dialogue_act=dialogue_act,
        modality_decision=modality_decision,
        selected_tools=selected_tools,
        clarification_required=needs_clarification,
        handoff_required=handoff_required,
        reason_parts=[
            object_routing.reason,
            dialogue_act.reason,
            modality_decision.reason,
            tool_selection_reason,
            clarification.reason if clarification is not None else "",
            handoff_reason,
            assembly_policy_reason,
        ],
    )

    route_name = "execution"
    if needs_clarification:
        route_name = "clarification"
    elif handoff_required:
        route_name = "handoff"

    return RoutingDecision(
        route_name=route_name,
        execution_intent=execution_intent,
        clarification=clarification,
        reason=execution_intent.reason,
    )


def build_execution_intent(routing_input: RoutingInput) -> ExecutionIntent:
    return route(routing_input).execution_intent


def _build_execution_intent(
    *,
    query: str,
    object_routing,
    dialogue_act,
    modality_decision,
    selected_tools,
    clarification_required: bool,
    handoff_required: bool,
    reason_parts: list[str],
) -> ExecutionIntent:
    primary_object = object_routing.primary_object or object_routing.active_object
    return ExecutionIntent(
        query=query,
        primary_object=primary_object,
        secondary_objects=list(object_routing.secondary_objects),
        ambiguous_objects=list(object_routing.ambiguous_objects),
        resolved_object_constraints=_resolved_object_constraints(primary_object),
        dialogue_act=dialogue_act,
        modality_decision=modality_decision,
        selected_tools=selected_tools,
        needs_clarification=clarification_required,
        handoff_required=handoff_required,
        reason=" ".join(part for part in reason_parts if part).strip(),
    )


def _resolved_object_constraints(primary_object) -> dict[str, str]:
    if primary_object is None:
        return {}
    constraints = {
        "object_type": primary_object.object_type,
        "canonical_value": primary_object.canonical_value,
        "display_name": primary_object.display_name,
        "identifier": primary_object.identifier,
        "identifier_type": primary_object.identifier_type,
        "business_line": primary_object.business_line,
    }
    return {key: value for key, value in constraints.items() if value}
