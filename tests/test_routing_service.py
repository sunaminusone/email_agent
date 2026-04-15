from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.models import (
    IngestionBundle,
    ParserContext,
    ParserRequestFlags,
    ParserSignals,
    TurnCore,
    TurnSignals,
)
from src.common.models import IntentGroup
from src.ingestion import build_demand_profile
from src.ingestion.demand_profile import narrow_demand_profile
from src.objects.models import AmbiguousObjectSet, ObjectCandidate, ResolvedObjectState
from src.routing.orchestrator import route
from src.routing.runtime import route_single_group


def test_product_inquiry_routes_to_execute():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What applications is this antibody validated for?",
            normalized_query="What applications is this antibody validated for?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="product_inquiry", intent_confidence=0.85)
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

    decision = route_single_group(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.action == "execute"
    assert decision.dialogue_act.act == "inquiry"
    assert decision.clarification is None


def test_service_inquiry_routes_to_execute():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What is your service plan for this workflow?",
            normalized_query="What is your service plan for this workflow?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="product_inquiry", intent_confidence=0.80)
            )
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

    decision = route_single_group(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.action == "execute"
    assert decision.dialogue_act.act == "inquiry"


def test_ambiguous_object_routes_to_clarify():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="Tell me about cd19",
            normalized_query="Tell me about cd19",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="product_inquiry", intent_confidence=0.80)
            )
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

    decision = route_single_group(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.action == "clarify"
    assert decision.clarification is not None


def test_order_tracking_routes_to_execute():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="Can you check the shipping status for order SO-12345?",
            normalized_query="Can you check the shipping status for order SO-12345?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="order_support", intent_confidence=0.90)
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

    decision = route_single_group(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.action == "execute"
    assert decision.dialogue_act.act == "inquiry"


def test_acknowledgement_routes_to_respond():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="Thanks, got it",
            normalized_query="Thanks, got it",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="unknown", intent_confidence=0.1)
            )
        ),
    )
    resolved = ResolvedObjectState(
        resolution_reason="No object found.",
    )

    decision = route_single_group(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.action == "respond"
    assert decision.dialogue_act.act == "closing"


def test_termination_routes_to_respond():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="bye",
            normalized_query="bye",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="unknown", intent_confidence=0.1)
            )
        ),
    )
    resolved = ResolvedObjectState(
        resolution_reason="No object found.",
    )

    decision = route_single_group(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.action == "respond"
    assert decision.dialogue_act.act == "closing"
    assert "parser_no_active_intent" in decision.dialogue_act.matched_signals


def test_technical_question_without_object_routes_to_execute():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What is the CAR-T cell therapy development workflow?",
            normalized_query="What is the CAR-T cell therapy development workflow?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="technical_question"),
                request_flags=ParserRequestFlags(needs_protocol=True),
            )
        ),
    )
    resolved = ResolvedObjectState(
        resolution_reason="No object found.",
    )
    focus_group = IntentGroup(
        intent="technical_question",
        request_flags=["needs_protocol"],
        confidence=0.8,
    )
    demand_profile = build_demand_profile(
        ingestion_bundle.turn_signals.parser_signals, [focus_group],
    )

    scoped_demand = narrow_demand_profile(demand_profile, focus_group)

    decision = route(
        ingestion_bundle, resolved,
        focus_group=focus_group, scoped_demand=scoped_demand,
    )

    assert decision.action == "execute"
    assert decision.dialogue_act.act == "inquiry"


def test_troubleshooting_without_object_routes_to_execute():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="How should I troubleshoot this product?",
            normalized_query="How should I troubleshoot this product?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="troubleshooting"),
                request_flags=ParserRequestFlags(needs_troubleshooting=True),
            )
        ),
    )
    resolved = ResolvedObjectState(
        resolution_reason="No object found.",
    )
    focus_group = IntentGroup(
        intent="troubleshooting",
        request_flags=["needs_troubleshooting"],
        confidence=0.8,
    )
    demand_profile = build_demand_profile(
        ingestion_bundle.turn_signals.parser_signals, [focus_group],
    )

    scoped_demand = narrow_demand_profile(demand_profile, focus_group)

    decision = route(
        ingestion_bundle, resolved,
        focus_group=focus_group, scoped_demand=scoped_demand,
    )

    assert decision.action == "execute"
    assert decision.dialogue_act.act == "inquiry"


def test_recommendation_without_object_routes_to_execute():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What technical recommendations do you have for this target?",
            normalized_query="What technical recommendations do you have for this target?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="technical_question"),
                request_flags=ParserRequestFlags(needs_recommendation=True),
            )
        ),
    )
    resolved = ResolvedObjectState(
        resolution_reason="No object found.",
    )
    focus_group = IntentGroup(
        intent="technical_question",
        request_flags=["needs_recommendation"],
        confidence=0.8,
    )
    demand_profile = build_demand_profile(
        ingestion_bundle.turn_signals.parser_signals, [focus_group],
    )

    scoped_demand = narrow_demand_profile(demand_profile, focus_group)

    decision = route(
        ingestion_bundle, resolved,
        focus_group=focus_group, scoped_demand=scoped_demand,
    )

    assert decision.action == "execute"
    assert decision.dialogue_act.act == "inquiry"


def test_high_risk_routes_to_handoff():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="I need to report a serious quality issue",
            normalized_query="I need to report a serious quality issue",
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
        resolution_reason="No object found.",
    )

    decision = route_single_group(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.action == "handoff"



def test_weak_technical_confidence_cannot_execute_without_object():
    """C3: demand_confidence < 0.3 blocks execution without object — routes to respond."""
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="hmm maybe something technical",
            normalized_query="hmm maybe something technical",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(context=ParserContext())
        ),
    )
    resolved = ResolvedObjectState(
        resolution_reason="No object found.",
    )
    focus_group = IntentGroup(
        intent="unknown",
        confidence=0.3,
    )
    demand_profile = build_demand_profile(
        ingestion_bundle.turn_signals.parser_signals, [focus_group],
    )
    # Verify confidence is indeed weak (0.4 from unknown intent, no flags)
    assert demand_profile.group_demands[0].demand_confidence < 0.5

    scoped_demand = narrow_demand_profile(demand_profile, focus_group)

    decision = route(
        ingestion_bundle, resolved,
        focus_group=focus_group, scoped_demand=scoped_demand,
    )

    # Without object AND weak confidence → cannot execute → respond
    assert decision.action == "respond"


def test_technical_with_resolved_object_routes_to_execute():
    """C4: Technical demand + resolved product object → execute (straightforward)."""
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="What is the protocol for this CD3 antibody?",
            normalized_query="What is the protocol for this CD3 antibody?",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="technical_question"),
                request_flags=ParserRequestFlags(needs_protocol=True),
            )
        ),
    )
    resolved = ResolvedObjectState(
        primary_object=ObjectCandidate(
            object_type="product",
            canonical_value="Anti-CD3 Antibody",
            display_name="Anti-CD3 Antibody",
            identifier="AB-100",
            identifier_type="catalog_number",
            confidence=0.95,
        ),
        resolution_reason="Selected the strongest current-turn object candidate.",
    )
    focus_group = IntentGroup(
        intent="technical_question",
        request_flags=["needs_protocol"],
        object_type="product",
        object_identifier="AB-100",
        object_display_name="Anti-CD3 Antibody",
        confidence=0.85,
    )
    demand_profile = build_demand_profile(
        ingestion_bundle.turn_signals.parser_signals, [focus_group],
    )

    scoped_demand = narrow_demand_profile(demand_profile, focus_group)

    decision = route(
        ingestion_bundle, resolved,
        focus_group=focus_group, scoped_demand=scoped_demand,
    )

    # Has object + technical demand → execute
    assert decision.action == "execute"
    assert decision.dialogue_act.act == "inquiry"


def test_elaboration_routes_to_execute_with_continuation():
    ingestion_bundle = IngestionBundle(
        turn_core=TurnCore(
            raw_query="Tell me more about this",
            normalized_query="Tell me more about this",
        ),
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                context=ParserContext(primary_intent="follow_up", intent_confidence=0.8)
            )
        ),
    )
    resolved = ResolvedObjectState(
        primary_object=ObjectCandidate(
            object_type="product",
            canonical_value="Anti-CD3 Antibody",
            display_name="Anti-CD3 Antibody",
            confidence=0.90,
        ),
        resolution_reason="Active object reused.",
    )

    decision = route_single_group(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved,
    )

    assert decision.action == "execute"
    assert decision.dialogue_act.act == "inquiry"
    assert decision.dialogue_act.is_continuation is True
