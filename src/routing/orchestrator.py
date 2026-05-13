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
        ingestion_bundle.turn_core.normalized_query or ingestion_bundle.turn_core.raw_query,
        parser_signals,
        object_routing,
        memory_context=ingestion_bundle.memory_context,
    )

    scoped_missing_information = _scope_missing_information(
        parser_signals.missing_information,
        focus_group=focus_group,
    )

    clarification = decide_clarification(
        object_routing,
        dialogue_act,
        missing_information=scoped_missing_information,
        missing_object_type=(focus_group.object_type if focus_group is not None else ""),
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

    if (
        scoped_demand.primary_demand == "technical"
        or "technical" in scoped_demand.secondary_demands
    ):
        return True

    # Timeline inquiries (e.g. "how long does protein expression take?")
    # can fall back to RAG generic process answers even without a
    # resolved object — pricing/quote/customization cannot.
    if "needs_timeline" in scoped_demand.request_flags:
        return True

    return False


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


def _scope_missing_information(
    missing_information: list[str],
    *,
    focus_group: IntentGroup | None,
) -> list[str]:
    if focus_group is None:
        return list(missing_information)

    object_type = focus_group.object_type
    if object_type == "order":
        allowed = {"order_number", "customer_identifier", "customer_name"}
    elif object_type == "invoice":
        allowed = {"invoice_number", "customer_identifier", "customer_name"}
    elif object_type == "shipment":
        allowed = {"order_number", "tracking_number", "customer_identifier", "customer_name"}
    else:
        return []

    return [item for item in missing_information if item in allowed]
