from __future__ import annotations

from src.common.models import DemandProfile, GroupDemand, IntentGroup
from src.ingestion.demand_profile import build_demand_profile, narrow_demand_profile
from src.routing.intent_assembly import assemble_intent_groups
from src.ingestion.models import IngestionBundle
from src.objects.models import ResolvedObjectState
from src.routing.models import RouteDecision
from src.routing.orchestrator import route



def route_single_group(
    *,
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    focus_group: IntentGroup | None = None,
    demand_profile: DemandProfile | None = None,
    scoped_demand: GroupDemand | None = None,
) -> RouteDecision:
    """Route a single intent group with demand-aware logic.

    When *scoped_demand* is provided it is used directly.  Otherwise
    it is computed here from the demand_profile — this is the only
    place outside service.py where narrow_demand_profile() is called,
    kept for test / standalone convenience.

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

    if scoped_demand is None:
        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

    return route(
        ingestion_bundle, resolved_object_state,
        focus_group=focus_group,
        scoped_demand=scoped_demand,
    )

