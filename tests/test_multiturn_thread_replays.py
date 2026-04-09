from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.conversation.agent_input_service import build_agent_input
from src.decision import route_agent_input
from src.orchestration.executor_service import execute_plan
from src.orchestration.planner_service import build_execution_plan
from src.rag.retriever import retrieve_chunks
from src.schemas import (
    Entities,
    ParsedContext,
    ParsedResult,
    RequestFlags,
    RuntimeContext,
)


def _history_with_route_state(route_state: dict, content: str = "Previous assistant message"):
    return [
        {
            "role": "assistant",
            "content": content,
            "metadata": {
                "route_state": route_state,
            },
        }
    ]


def _parsed(
    *,
    primary_intent: str = "unknown",
    product_names=None,
    service_names=None,
    targets=None,
    needs_documentation: bool = False,
    needs_timeline: bool = False,
):
    return ParsedResult(
        context=ParsedContext(primary_intent=primary_intent),
        entities=Entities(
            product_names=product_names or [],
            service_names=service_names or [],
            targets=targets or [],
        ),
        request_flags=RequestFlags(
            needs_documentation=needs_documentation,
            needs_timeline=needs_timeline,
        ),
    )


def test_service_follow_up_reuses_active_service_for_models_query():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "mrna_lnp",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "",
                    "identifier_type": "",
                    "entity_kind": "service",
                    "display_name": "mRNA-LNP Gene Delivery",
                    "business_line": "mrna_lnp",
                },
                "active_service_name": "mRNA-LNP Gene Delivery",
                "active_business_line": "mrna_lnp",
            },
        }
    )
    agent = build_agent_input(
        "thread-service-1",
        "What models do you support?",
        _parsed(primary_intent="follow_up"),
        history,
        [],
    )

    result = retrieve_chunks(
        query=agent.query,
        top_k=3,
        business_line_hint=agent.active_business_line,
        active_service_name=agent.active_service_name,
    )

    top_match = result["matches"][0]["metadata"]
    assert agent.active_service_name == "mRNA-LNP Gene Delivery"
    assert top_match.get("service_name") == "mRNA-LNP Gene Delivery"
    assert top_match.get("section_type") == "model_support"


def test_broad_service_question_without_context_requests_follow_up():
    agent = build_agent_input(
        "thread-service-2",
        "What models do you support?",
        _parsed(primary_intent="technical_question"),
        [],
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name == "clarification_request"
    assert routed.route.missing_information_to_request
    assert "which service" in routed.route.missing_information_to_request[0].lower()


def test_product_document_follow_up_reuses_active_product_context():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "antibody",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "20001",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Mouse Monoclonal antibody to Nucleophosmin",
                    "business_line": "antibody",
                },
                "active_product_name": "Mouse Monoclonal antibody to Nucleophosmin",
                "active_business_line": "antibody",
            },
        }
    )
    agent = build_agent_input(
        "thread-product-1",
        "send me the brochure",
        _parsed(primary_intent="follow_up", needs_documentation=True),
        history,
        [],
    )

    assert agent.turn_resolution.turn_type == "follow_up"
    assert agent.entities.catalog_numbers == ["20001"]
    assert agent.active_product_name == "Mouse Monoclonal antibody to Nucleophosmin"


def test_active_product_follow_up_does_not_trigger_service_clarification():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "antibody",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "20001",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Mouse Monoclonal antibody to Nucleophosmin",
                    "business_line": "antibody",
                },
                "active_product_name": "Mouse Monoclonal antibody to Nucleophosmin",
                "active_target": "Nucleophosmin",
                "active_business_line": "antibody",
            },
        }
    )
    agent = build_agent_input(
        "thread-product-2",
        "What applications do you support?",
        _parsed(primary_intent="follow_up"),
        history,
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name != "clarification_request"


def test_service_switch_replaces_active_service_before_phase_follow_up():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "mrna_lnp",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "",
                    "identifier_type": "",
                    "entity_kind": "service",
                    "display_name": "mRNA-LNP Gene Delivery",
                    "business_line": "mrna_lnp",
                },
                "active_service_name": "mRNA-LNP Gene Delivery",
                "active_business_line": "mrna_lnp",
            },
        }
    )
    first_turn = build_agent_input(
        "thread-switch-1",
        "tell me about Custom CAR-Macrophage Cell Development",
        _parsed(primary_intent="general_info", service_names=["Custom CAR-Macrophage Cell Development"]),
        history,
        [],
    )
    result = retrieve_chunks(
        query="How long is Phase IV?",
        top_k=3,
        business_line_hint=first_turn.active_business_line,
        active_service_name=first_turn.active_service_name,
    )

    top_match = result["matches"][0]["metadata"]
    assert first_turn.active_service_name == "Custom CAR-Macrophage Cell Development"
    assert first_turn.active_business_line == "car_t_car_nk"
    assert top_match.get("service_name") == "Custom CAR-Macrophage Cell Development"
    assert top_match.get("section_type") == "service_phase"


def test_phase_follow_up_with_active_service_hits_exact_phase_first():
    result = retrieve_chunks(
        query="How long is Phase IV?",
        top_k=3,
        business_line_hint="car_t_car_nk",
        active_service_name="Custom CAR-Macrophage Cell Development",
    )

    top_match = result["matches"][0]["metadata"]
    assert top_match.get("service_name") == "Custom CAR-Macrophage Cell Development"
    assert top_match.get("section_type") == "service_phase"
    assert top_match.get("phase_name") == "Phase IV"


def test_service_plan_follow_up_with_active_service_executes_technical_retrieval():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "mrna_lnp",
            "active_engagement_type": "service_inquiry",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "",
                    "identifier_type": "",
                    "entity_kind": "service",
                    "display_name": "mRNA-LNP Gene Delivery",
                    "business_line": "mrna_lnp",
                },
                "active_service_name": "mRNA-LNP Gene Delivery",
                "active_business_line": "mrna_lnp",
                "last_user_goal": "request_technical_information",
            },
        }
    )
    agent = build_agent_input(
        "thread-service-plan-1",
        "What is the service plan?",
        _parsed(primary_intent="follow_up"),
        history,
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))
    plan = build_execution_plan(agent, routed.route)
    run = execute_plan(agent, plan)

    technical_action = next(
        (action for action in run.executed_actions if action.action_type == "retrieve_technical_knowledge"),
        None,
    )

    assert technical_action is not None
    assert technical_action.output["retrieval_debug"]["effective_scope_type"] == "service"
    assert technical_action.output["retrieval_debug"]["rewritten_query"] == "What is the service plan for mRNA-LNP Gene Delivery?"
    top_labels = [match["chunk_label"] for match in technical_action.output["matches"][:3]]
    assert any("Discovery Services Plan" in label for label in top_labels)
