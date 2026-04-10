from __future__ import annotations

from src.ingestion.models import IngestionBundle
from src.objects.models import ResolvedObjectState
from src.routing.models import ExecutionIntent, RoutingDecision, RoutingInput
from src.routing.orchestrator import build_execution_intent, route


def build_routing_input_from_ingestion(
    *,
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
) -> RoutingInput:
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


def route_from_ingestion_bundle(
    *,
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
) -> RoutingDecision:
    return route(
        build_routing_input_from_ingestion(
            ingestion_bundle=ingestion_bundle,
            resolved_object_state=resolved_object_state,
        )
    )


def build_execution_intent_from_ingestion_bundle(
    *,
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
) -> ExecutionIntent:
    return build_execution_intent(
        build_routing_input_from_ingestion(
            ingestion_bundle=ingestion_bundle,
            resolved_object_state=resolved_object_state,
        )
    )
