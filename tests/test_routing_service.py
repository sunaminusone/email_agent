from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.models import IngestionBundle, ParserContext, ParserSignals, TurnCore, TurnSignals
from src.objects.models import AmbiguousObjectSet, ObjectCandidate, ResolvedObjectState
from src.routing.runtime import (
    build_execution_intent_from_ingestion_bundle,
    build_routing_input_from_ingestion,
    route_from_ingestion_bundle,
)


def test_product_technical_question_routes_to_hybrid_tools():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What applications is this antibody validated for?",
            normalized_query="What applications is this antibody validated for?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(context=ParserContext())
        ),
    )
    resolved = ResolvedObjectState(
        primary_object=ObjectCandidate(
            object_type="product",
            canonical_value="Rabbit Polyclonal antibody to MSH2",
            display_name="Rabbit Polyclonal antibody to MSH2",
            identifier="P06329",
            identifier_type="catalog_number",
            confidence=0.95,
        ),
        resolution_reason="Selected the strongest current-turn object candidate.",
    )

    intent = build_execution_intent_from_ingestion_bundle(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert intent.dialogue_act.act == "INQUIRY"
    assert intent.modality_decision.primary_modality == "hybrid"
    assert intent.selected_tools == ["catalog_lookup_tool", "technical_rag_tool"]
    assert intent.needs_clarification is False


def test_service_plan_routes_to_technical_rag():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What is your service plan for this workflow?",
            normalized_query="What is your service plan for this workflow?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(context=ParserContext())
        ),
    )
    resolved = ResolvedObjectState(
        primary_object=ObjectCandidate(
            object_type="service",
            canonical_value="Flow Cytometry Services",
            display_name="Flow Cytometry Services",
            confidence=0.91,
        ),
        resolution_reason="Selected the strongest current-turn object candidate.",
    )

    intent = build_execution_intent_from_ingestion_bundle(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert intent.modality_decision.primary_modality == "unstructured_retrieval"
    assert intent.selected_tools == ["technical_rag_tool"]


def test_ambiguous_object_routes_to_clarification():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="Tell me about cd19",
            normalized_query="Tell me about cd19",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(context=ParserContext())
        ),
    )
    resolved = ResolvedObjectState(
        ambiguous_sets=[
            AmbiguousObjectSet(
                object_type="product",
                query_value="cd19",
                candidates=[
                    ObjectCandidate(object_type="product", display_name="Human CD19 Antibody"),
                    ObjectCandidate(object_type="product", display_name="Mouse CD19 Antibody"),
                ],
            )
        ],
        resolution_reason="No primary object was selected because clarification-worthy ambiguity remains.",
    )

    intent = build_execution_intent_from_ingestion_bundle(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert intent.needs_clarification is True
    assert intent.selected_tools == []


def test_order_tracking_routes_to_external_tools():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="Can you check the shipping status for order SO-12345?",
            normalized_query="Can you check the shipping status for order SO-12345?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(context=ParserContext())
        ),
    )
    resolved = ResolvedObjectState(
        primary_object=ObjectCandidate(
            object_type="order",
            display_name="Order SO-12345",
            identifier="SO-12345",
            identifier_type="order_number",
            confidence=0.94,
        ),
        resolution_reason="Selected the strongest current-turn object candidate.",
    )

    intent = build_execution_intent_from_ingestion_bundle(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert intent.modality_decision.primary_modality == "external_api"
    assert intent.selected_tools == ["order_lookup_tool", "shipping_lookup_tool"]


def test_runtime_returns_routing_decision_directly():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What applications is this antibody validated for?",
            normalized_query="What applications is this antibody validated for?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(context=ParserContext())
        ),
    )
    resolved = ResolvedObjectState(
        primary_object=ObjectCandidate(
            object_type="product",
            canonical_value="Rabbit Polyclonal antibody to MSH2",
            display_name="Rabbit Polyclonal antibody to MSH2",
            identifier="P06329",
            identifier_type="catalog_number",
            confidence=0.95,
        ),
        resolution_reason="Selected the strongest current-turn object candidate.",
    )

    decision = route_from_ingestion_bundle(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.route_name == "execution"
    assert decision.execution_intent.selected_tools == ["catalog_lookup_tool", "technical_rag_tool"]


def test_runtime_projects_routing_input_from_ingestion_bundle():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What applications is this antibody validated for?",
            normalized_query="What applications is this antibody validated for?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(
                    risk_level="high",
                    needs_human_review=True,
                )
            )
        ),
    )
    resolved = ResolvedObjectState(
        primary_object=ObjectCandidate(
            object_type="product",
            canonical_value="Rabbit Polyclonal antibody to MSH2",
            display_name="Rabbit Polyclonal antibody to MSH2",
            identifier="P06329",
            identifier_type="catalog_number",
            confidence=0.95,
        ),
        resolution_reason="Selected the strongest current-turn object candidate.",
    )

    routing_input = build_routing_input_from_ingestion(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert routing_input.query == "What applications is this antibody validated for?"
    assert routing_input.risk_level == "high"
    assert routing_input.needs_human_review is True


def test_runtime_can_route_directly_from_ingestion_bundle():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="Can you check the shipping status for order SO-12345?",
            normalized_query="Can you check the shipping status for order SO-12345?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(
                    risk_level="low",
                    needs_human_review=False,
                )
            )
        ),
    )
    resolved = ResolvedObjectState(
        primary_object=ObjectCandidate(
            object_type="order",
            display_name="Order SO-12345",
            identifier="SO-12345",
            identifier_type="order_number",
            confidence=0.94,
        ),
        resolution_reason="Selected the strongest current-turn object candidate.",
    )

    decision = route_from_ingestion_bundle(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )
    intent = build_execution_intent_from_ingestion_bundle(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.route_name == "execution"
    assert intent.selected_tools == ["order_lookup_tool", "shipping_lookup_tool"]
