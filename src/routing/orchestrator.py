from __future__ import annotations

from src.common.models import DemandProfile, IntentGroup
from src.ingestion.models import IngestionBundle
from src.ingestion.demand_profile import narrow_demand_profile
from src.objects.models import ResolvedObjectState
from src.routing.models import RouteDecision
from src.routing.policies import decide_clarification, decide_handoff
from src.routing.stages import resolve_dialogue_act, resolve_object_routing


def route(
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    *,
    focus_group: IntentGroup | None = None,
    demand_profile: DemandProfile | None = None,
) -> RouteDecision:
    """Route a customer message to an action: execute / respond / clarify / handoff.

    When *focus_group* is provided the routing decision is scoped to that
    single intent group.  Missing-information checks are narrowed to the
    group's object type so that a clarification needed by one group does
    not block execution of another.
    """
    parser_signals = ingestion_bundle.turn_signals.parser_signals
    query = (
        ingestion_bundle.turn_core.normalized_query
        or ingestion_bundle.turn_core.raw_query
        or ""
    )

    object_routing = resolve_object_routing(resolved_object_state)
    dialogue_act = resolve_dialogue_act(
        query,
        object_routing,
        stateful_anchors=ingestion_bundle.stateful_anchors,
    )

    missing_information = _narrow_missing_information(
        parser_signals.missing_information, focus_group,
    )

    clarification = decide_clarification(
        object_routing,
        dialogue_act,
        missing_information=missing_information or None,
    )
    handoff_required, handoff_reason = decide_handoff(
        risk_level=parser_signals.context.risk_level,
        needs_human_review=parser_signals.context.needs_human_review,
    )

    has_object = (
        object_routing.primary_object is not None
        or object_routing.active_object is not None
    )
    can_execute_without_object = _can_execute_without_object(
        focus_group=focus_group,
        demand_profile=demand_profile,
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


def _narrow_missing_information(
    missing_information: list[str] | None,
    focus_group: IntentGroup | None,
) -> list[str] | None:
    """When routing a specific intent group, only surface missing info
    relevant to that group's object type and request flags."""
    if focus_group is None or not missing_information:
        return missing_information

    # Map object types to their critical field prefixes
    relevant_prefixes: dict[str, set[str]] = {
        "order": {"order_number", "customer_identifier"},
        "invoice": {"invoice_number", "customer_identifier"},
        "shipment": {"order_number", "tracking_number"},
    }

    allowed = relevant_prefixes.get(focus_group.object_type, set())
    if not allowed:
        return None

    narrowed = [info for info in missing_information if info in allowed]
    return narrowed or None

def _can_execute_without_object(
    *,
    focus_group: IntentGroup | None,
    demand_profile: DemandProfile | None,
) -> bool:
    """Decide if execution can proceed without a resolved object.

    Reads only from GroupDemand (the semantic layer) — raw request_flags
    and primary_intent are builder inputs, not routing judgment sources.
    """
    scoped_demand = narrow_demand_profile(demand_profile, focus_group)
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
