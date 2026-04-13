from __future__ import annotations

from src.common.models import DemandProfile, IntentGroup
from src.ingestion.demand_profile import build_demand_profile
from src.ingestion.intent_assembly import assemble_intent_groups
from src.ingestion.models import IngestionBundle
from src.objects.models import ResolvedObjectState
from src.routing.models import RouteDecision, RoutingInput
from src.routing.orchestrator import route


def build_routing_input_from_ingestion(
    *,
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
) -> RoutingInput:
    """Build a RoutingInput from ingestion + object resolution outputs."""
    parser_context = ingestion_bundle.turn_signals.parser_signals.context
    query = (
        ingestion_bundle.turn_core.normalized_query
        or ingestion_bundle.turn_core.raw_query
        or ""
    )
    return RoutingInput(
        query=query,
        resolved_object_state=resolved_object_state,
        risk_level=parser_context.risk_level,
        needs_human_review=parser_context.needs_human_review,
    )


def route_single_group(
    *,
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    focus_group: IntentGroup | None = None,
    demand_profile: DemandProfile | None = None,
) -> RouteDecision:
    """Route a single intent group with demand-aware logic.

    When *demand_profile* is not provided, auto-builds one from the
    ingestion bundle.  When *focus_group* is also absent, defaults to
    the first assembled intent group.

    For multi-group (turn-level) routing, use the agent loop in
    service.py which calls route() per group independently.
    """
    if demand_profile is None:
        parser_signals = ingestion_bundle.turn_signals.parser_signals
        resolved_objects = [
            resolved_object_state.primary_object,
            *resolved_object_state.secondary_objects,
        ]
        intent_groups = assemble_intent_groups(
            request_flags=parser_signals.request_flags,
            resolved_objects=resolved_objects,
            primary_intent=parser_signals.context.primary_intent,
        )
        demand_profile = build_demand_profile(parser_signals, intent_groups)

        if focus_group is None and intent_groups:
            focus_group = intent_groups[0]

    return route(
        ingestion_bundle, resolved_object_state,
        focus_group=focus_group,
        demand_profile=demand_profile,
    )


# Backward-compatible alias
route_v3_from_ingestion_bundle = route_single_group
