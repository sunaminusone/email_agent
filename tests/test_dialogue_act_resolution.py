from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.conversation.agent_input_service import build_agent_input
from src.decision.response_service import build_response_artifacts, generate_final_response
from src.orchestration.prototype_service import _build_route_state
from src.schemas import (
    Entities,
    ExecutedAction,
    ExecutionRun,
    OpenSlots,
    ParsedContext,
    ParsedResult,
    RequestFlags,
    RouteDecision,
    RuntimeContext,
)


def _history_with_route_state(route_state: dict, content: str = "Previous assistant message"):
    return [
        {
            "role": "assistant",
            "content": content,
            "metadata": {
                "route_state": route_state,
                "content_blocks": [
                    {"kind": "product_identity"},
                    {"kind": "application"},
                    {"kind": "species_reactivity"},
                ],
                "response_type": "answer",
            },
        }
    ]


def _parsed(
    *,
    primary_intent: str = "follow_up",
    product_names: list[str] | None = None,
    catalog_numbers: list[str] | None = None,
    service_names: list[str] | None = None,
    targets: list[str] | None = None,
):
    return ParsedResult(
        context=ParsedContext(primary_intent=primary_intent),
        entities=Entities(
            product_names=list(product_names or []),
            catalog_numbers=list(catalog_numbers or []),
            service_names=list(service_names or []),
            targets=list(targets or []),
        ),
        request_flags=RequestFlags(),
        open_slots=OpenSlots(),
    )


def _route(route_name: str = "commercial_agent", business_line: str = "antibody"):
    return RouteDecision(
        route_name=route_name,
        business_line=business_line,
        engagement_type="catalog_product",
        route_confidence=0.96,
    )


def _product_match():
    return {
        "catalog_no": "P06329",
        "name": "Rabbit Polyclonal antibody to MSH2",
        "display_name": "Rabbit Polyclonal antibody to MSH2",
        "business_line": "Antibody",
        "target_antigen": "MSH2",
        "application_text": "ELISA, WB, IHC",
        "species_reactivity_text": "Human, Mouse",
        "matched_field": "catalog_no",
        "match_rank": 200,
    }


def _product_history(*, revealed_attributes: list[str] | None = None):
    return _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "antibody",
            "active_engagement_type": "catalog_product",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "P06329",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Rabbit Polyclonal antibody to MSH2",
                    "business_line": "antibody",
                },
                "active_product_name": "Rabbit Polyclonal antibody to MSH2",
                "active_business_line": "antibody",
                "revealed_attributes": list(revealed_attributes or []),
            },
        }
    )


def _execution_run():
    return ExecutionRun(
        plan_goal="Provide product details",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={"matches": [_product_match()]},
            ),
        ],
    )


def test_acknowledge_follow_up_does_not_repeat_product_details():
    agent = build_agent_input(
        "ack-thread",
        "ok",
        _parsed(),
        _product_history(revealed_attributes=["identity", "application", "species_reactivity"]),
        [],
    )
    execution_run = _execution_run()
    artifacts = build_response_artifacts(RuntimeContext(agent_context=agent), _route(), execution_run)
    response = artifacts["final_response"]
    assert artifacts["response_resolution"].dialogue_act == "ACKNOWLEDGE"
    assert response.response_type == "acknowledgement"
    assert "best product match" not in response.message.lower()
    assert "applications" in response.message.lower()


def test_mixed_acknowledgement_with_business_question_becomes_inquiry():
    agent = build_agent_input(
        "mixed-ack-thread",
        "ok, applications?",
        _parsed(),
        _product_history(),
        [],
    )
    execution_run = _execution_run()
    artifacts = build_response_artifacts(RuntimeContext(agent_context=agent), _route(), execution_run)
    resolution = artifacts["response_resolution"]
    response = artifacts["final_response"]
    assert resolution.dialogue_act == "INQUIRY"
    assert resolution.answer_focus in {"product_identity", "product_elaboration"}
    assert "applications include" in response.message.lower()


def test_terminate_follow_up_soft_resets_product_state():
    agent = build_agent_input(
        "stop-thread",
        "stop",
        _parsed(),
        _product_history(revealed_attributes=["identity", "application"]),
        [],
    )
    execution_run = _execution_run()
    artifacts = build_response_artifacts(RuntimeContext(agent_context=agent), _route(), execution_run)
    response = artifacts["final_response"]
    resolution = artifacts["response_resolution"]
    route_state = _build_route_state(agent, _route(), response, resolution)

    assert resolution.dialogue_act == "TERMINATE"
    assert response.response_type == "conversation_close"
    assert route_state["session_payload"]["active_product_name"] == ""
    assert route_state["session_payload"]["revealed_attributes"] == []
    assert route_state["session_payload"]["pending_clarification"]["field"] == ""


def test_elaborate_without_new_grounded_fields_avoids_repeating_same_product_answer():
    agent = build_agent_input(
        "elaborate-thread",
        "do you have more information?",
        _parsed(),
        _product_history(revealed_attributes=["identity", "target_antigen", "application", "species_reactivity"]),
        [],
    )
    execution_run = _execution_run()
    response = generate_final_response(RuntimeContext(agent_context=agent), _route(), execution_run)
    assert "best product match" not in response.message.lower()
    assert "main grounded product details" in response.message.lower()
