from __future__ import annotations

from src.common.models import GroupDemand, IntentGroup
from src.ingestion.models import IngestionBundle
from src.objects.models import ResolvedObjectState
from src.routing.models import RouteDecision
from src.routing.policies import decide_clarification, decide_handoff
from src.routing.stages import resolve_dialogue_act, resolve_object_routing


def route(
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    *,
    focus_group: IntentGroup | None = None,
    scoped_demand: GroupDemand | None = None,
) -> RouteDecision:
    """Route a customer message to an action: execute / respond / clarify / handoff.

    *scoped_demand* must be pre-computed by the caller (service.py agent
    loop) and passed in directly.  This ensures routing and executor see
    the exact same GroupDemand instance — no silent re-derivation.

    When *focus_group* is provided the routing decision is scoped to that
    single intent group.  Missing-information checks are narrowed to the
    group's object type so that a clarification needed by one group does
    not block execution of another.
    """

    parser_signals = ingestion_bundle.turn_signals.parser_signals

    object_routing = resolve_object_routing(resolved_object_state)
    dialogue_act = resolve_dialogue_act(
        parser_signals,
        stateful_anchors=ingestion_bundle.stateful_anchors,
    )

    clarification = decide_clarification(object_routing, dialogue_act)
    handoff_required, handoff_reason = decide_handoff(
        risk_level=parser_signals.context.risk_level,
        needs_human_review=parser_signals.context.needs_human_review,
    )

    has_object = (
        object_routing.primary_object is not None
        or object_routing.active_object is not None
    )
    can_execute_without_object = _can_execute_without_object(
        scoped_demand=scoped_demand,
    )
    action = _determine_action(
        dialogue_act,
        clarification,
        handoff_required,
        has_object,
        can_execute_without_object,
    )

    reason_parts = [
        object_routing.reason,
        dialogue_act.reason,
        handoff_reason,
        clarification.reason if clarification is not None else "",
    ]

    return RouteDecision(
        action=action,
        dialogue_act=dialogue_act,
        clarification=clarification,
        reason=" ".join(part for part in reason_parts if part).strip(),
    )


def _can_execute_without_object(
    *,
    scoped_demand: GroupDemand | None,
) -> bool:
    """Decide if execution can proceed without a resolved object.

    Reads only from GroupDemand (the semantic layer) — raw request_flags
    and semantic_intent are builder inputs, not routing judgment sources.
    """
    if scoped_demand is None:
        return False

    if scoped_demand.demand_confidence < 0.3:
        return False

    return (
        scoped_demand.primary_demand == "technical"
        or "technical" in scoped_demand.secondary_demands
    )


def _determine_action(
    dialogue_act,
    clarification,
    handoff_required: bool,
    has_object: bool,
    can_execute_without_object: bool,
) -> str:
    if handoff_required:
        return "handoff"
    if clarification is not None:
        return "clarify"
    if dialogue_act.act == "closing":
        return "respond"
    if has_object or can_execute_without_object:
        return "execute"
    return "respond"
