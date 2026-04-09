from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.schemas import (
    ActiveEntityPayload,
    Entities,
    ParsedContext,
    ParsedResult,
    PersistedSessionPayload,
    RequestFlags,
)
from src.conversation.agent_input_service import build_agent_input


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
    catalog_numbers=None,
    order_numbers=None,
    product_names=None,
    service_names=None,
    targets=None,
    needs_documentation: bool = False,
    needs_timeline: bool = False,
    needs_invoice: bool = False,
    needs_order_status: bool = False,
    needs_price: bool = False,
    needs_quote: bool = False,
):
    return ParsedResult(
        context=ParsedContext(primary_intent=primary_intent),
        entities=Entities(
            catalog_numbers=catalog_numbers or [],
            order_numbers=order_numbers or [],
            product_names=product_names or [],
            service_names=service_names or [],
            targets=targets or [],
        ),
        request_flags=RequestFlags(
            needs_documentation=needs_documentation,
            needs_timeline=needs_timeline,
            needs_invoice=needs_invoice,
            needs_order_status=needs_order_status,
            needs_price=needs_price,
            needs_quote=needs_quote,
        ),
    )


def test_clarification_answer_reuses_pending_product_identifier():
    history = _history_with_route_state(
        {
            "active_route": "clarification_request",
            "pending_route_after_clarification": "commercial_agent",
            "route_phase": "waiting_for_user",
            "pending_identifiers": ["20001"],
            "session_payload": {
                "pending_clarification": {
                    "field": "identifier_type",
                    "candidate_identifier": "20001",
                    "question": "Please confirm whether 20001 is a product/catalog number or an invoice/order number.",
                }
            },
        },
        "Please confirm whether 20001 is a product/catalog number or an invoice/order number.",
    )
    agent = build_agent_input("t1", "it's a product", _parsed(primary_intent="follow_up"), history, [])
    assert agent.turn_resolution.turn_type == "clarification_answer"
    assert agent.entities.catalog_numbers == ["20001"]
    assert agent.effective_query == "product 20001"


def test_clarification_answer_reuses_pending_invoice_identifier():
    history = _history_with_route_state(
        {
            "active_route": "clarification_request",
            "pending_route_after_clarification": "operational_agent",
            "route_phase": "waiting_for_user",
            "pending_identifiers": ["54321"],
            "session_payload": {
                "pending_clarification": {
                    "field": "identifier_type",
                    "candidate_identifier": "54321",
                    "question": "Please confirm whether 54321 is a product/catalog number or an invoice/order number.",
                }
            },
        }
    )
    agent = build_agent_input("t2", "it's an invoice", _parsed(primary_intent="follow_up"), history, [])
    assert agent.turn_resolution.turn_type == "clarification_answer"
    assert agent.entities.order_numbers == ["54321"]
    assert agent.effective_query == "invoice 54321"


def test_product_selection_clarification_reuses_selected_catalog_number():
    history = _history_with_route_state(
        {
            "active_route": "clarification_request",
            "route_phase": "waiting_for_user",
            "pending_identifiers": ["20025", "31785", "P06329"],
            "session_payload": {
                "pending_clarification": {
                    "field": "product_selection",
                    "candidate_identifier": "",
                    "candidate_options": ["20025", "31785", "P06329"],
                    "question": 'I found multiple products matching "MSH2". Please choose one:\n- 20025 | Mouse Monoclonal Antibody to MSH2\n- 31785 | Mouse Monoclonal Antibody to MSH2\n- P06329 | Rabbit Polyclonal antibody to MSH2\nYou can reply with the catalog number only.',
                }
            },
        },
        'I found multiple products matching "MSH2". Please choose one:\n- 20025 | Mouse Monoclonal Antibody to MSH2\n- 31785 | Mouse Monoclonal Antibody to MSH2\n- P06329 | Rabbit Polyclonal antibody to MSH2\nYou can reply with the catalog number only.',
    )
    agent = build_agent_input("t3", "20025", _parsed(primary_intent="follow_up"), history, [])
    assert agent.turn_resolution.turn_type == "clarification_answer"
    assert agent.entities.catalog_numbers == ["20025"]
    assert agent.interpreted_payload.confirmed_identifier_type == "catalog_number"
    assert "catalog number 20025" in agent.retrieval_query.lower()


def test_follow_up_lead_time_reuses_active_entity():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "antibody",
            "active_engagement_type": "catalog_product",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "20001",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Mouse Monoclonal antibody to Nucleophosmin",
                    "business_line": "antibody",
                },
                "active_business_line": "antibody",
                "last_user_goal": "request_product_information",
            },
        }
    )
    agent = build_agent_input(
        "t3",
        "what about the lead time?",
        _parsed(primary_intent="follow_up", needs_timeline=True),
        history,
        [],
    )
    assert agent.turn_resolution.turn_type == "follow_up"
    assert agent.entities.catalog_numbers == ["20001"]
    assert agent.effective_query == "lead time for 20001"


def test_explicit_new_request_resets_previous_workflow():
    history = _history_with_route_state(
        {
            "active_route": "workflow_agent",
            "active_business_line": "car_t",
            "active_engagement_type": "custom_service",
            "route_phase": "active",
            "session_payload": {
                "active_business_line": "car_t",
                "last_user_goal": "request_customization",
            },
        }
    )
    agent = build_agent_input(
        "t4",
        "can you give me some information about baculovirus",
        _parsed(primary_intent="general_info", service_names=["Baculovirus Expression"]),
        history,
        [],
    )
    assert agent.turn_resolution.turn_type == "new_request"
    assert agent.turn_resolution.should_reuse_active_route is False
    assert agent.turn_resolution.should_reset_route_context is True


def test_business_line_shift_resets_context():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "antibody",
            "active_engagement_type": "catalog_product",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "20001",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Mouse Monoclonal antibody",
                    "business_line": "antibody",
                },
                "active_business_line": "antibody",
            },
        }
    )
    agent = build_agent_input(
        "t5",
        "can you share a CAR-T brochure?",
        _parsed(primary_intent="documentation_request", needs_documentation=True),
        history,
        [],
    )
    assert agent.turn_resolution.turn_type == "new_request"
    assert agent.turn_resolution.resolved_business_line == "car_t"


def test_technical_query_with_catalog_identifier_prefers_product_interpretation():
    agent = build_agent_input(
        "t5b",
        "do you have a protocol for ELISA with 20001",
        _parsed(primary_intent="technical_question"),
        [],
        [],
    )
    assert agent.entities.catalog_numbers == ["20001"]
    assert agent.product_lookup_keys.ambiguous_identifiers == []
    assert agent.request_flags.needs_documentation is True


def test_reference_resolution_other_one_uses_recent_entity():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "antibody",
            "active_engagement_type": "catalog_product",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "20002",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Product Two",
                    "business_line": "antibody",
                },
                "recent_entities": [
                    {
                        "identifier": "20002",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product Two",
                        "business_line": "antibody",
                    },
                    {
                        "identifier": "20001",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product One",
                        "business_line": "antibody",
                    },
                ],
                "active_business_line": "antibody",
                "last_user_goal": "request_product_information",
            },
        }
    )
    agent = build_agent_input("t6", "what about the other one?", _parsed(primary_intent="follow_up"), history, [])
    assert agent.reference_resolution.resolved_identifier == "20001"
    assert agent.reference_resolution.resolved_identifiers == ["20001"]
    assert agent.reference_resolution.resolution_mode == "other_recent_entity"
    assert agent.entities.catalog_numbers == ["20001"]
    assert agent.interpreted_payload.reference_resolution == "20001"


def test_reference_resolution_first_one_uses_first_recent_entity():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "route_phase": "active",
            "session_payload": {
                "recent_entities": [
                    {
                        "identifier": "20001",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product One",
                        "business_line": "antibody",
                    },
                    {
                        "identifier": "20002",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product Two",
                        "business_line": "antibody",
                    },
                ],
            },
        }
    )
    agent = build_agent_input("t7", "show me the first one", _parsed(primary_intent="follow_up"), history, [])
    assert agent.reference_resolution.resolved_identifier == "20001"
    assert agent.entities.catalog_numbers == ["20001"]


def test_reference_resolution_second_one_uses_second_recent_entity():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "route_phase": "active",
            "session_payload": {
                "recent_entities": [
                    {
                        "identifier": "20001",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product One",
                        "business_line": "antibody",
                    },
                    {
                        "identifier": "20002",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product Two",
                        "business_line": "antibody",
                    },
                ],
            },
        }
    )
    agent = build_agent_input("t8", "show me the second one", _parsed(primary_intent="follow_up"), history, [])
    assert agent.reference_resolution.resolved_identifier == "20002"
    assert agent.entities.catalog_numbers == ["20002"]


def test_same_product_phrase_reuses_active_entity():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "20001",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Product One",
                    "business_line": "antibody",
                },
                "active_business_line": "antibody",
            },
        }
    )
    agent = build_agent_input("t9", "same product, but brochure please", _parsed(primary_intent="follow_up", needs_documentation=True), history, [])
    assert agent.reference_resolution.resolved_identifier == "20001"
    assert agent.turn_resolution.turn_type == "follow_up"


def test_reference_resolution_all_recent_entities_preserves_multiple_identifiers():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "route_phase": "active",
            "session_payload": {
                "recent_entities": [
                    {
                        "identifier": "20002",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product Two",
                        "business_line": "antibody",
                    },
                    {
                        "identifier": "20001",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product One",
                        "business_line": "antibody",
                    },
                ],
            },
        }
    )
    agent = build_agent_input("t9b", "what about both of them?", _parsed(primary_intent="follow_up"), history, [])
    assert agent.reference_resolution.resolution_mode == "all_recent_entities"
    assert agent.reference_resolution.resolved_identifiers == ["20002", "20001"]
    assert agent.entities.catalog_numbers == ["20002", "20001"]
    assert agent.interpreted_payload.reference_resolutions == ["20002", "20001"]


def test_recent_entities_are_updated_when_new_identifier_arrives():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "20001",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Product One",
                    "business_line": "antibody",
                },
                "recent_entities": [
                    {
                        "identifier": "20001",
                        "identifier_type": "catalog_number",
                        "entity_kind": "product",
                        "display_name": "Product One",
                        "business_line": "antibody",
                    }
                ],
                "active_business_line": "antibody",
            },
        }
    )
    agent = build_agent_input(
        "t10",
        "product 20002",
        _parsed(primary_intent="product_inquiry", catalog_numbers=["20002"]),
        history,
        [],
    )
    assert agent.session_payload.active_entity.identifier == "20002"
    assert [entity.identifier for entity in agent.session_payload.recent_entities[:2]] == ["20002", "20001"]


def test_generic_document_request_does_not_reuse_old_entity_payload():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "20001",
                    "identifier_type": "catalog_number",
                    "entity_kind": "product",
                    "display_name": "Product One",
                    "business_line": "antibody",
                },
                "active_business_line": "antibody",
            },
        }
    )
    agent = build_agent_input(
        "t11",
        "can you give me a brochure",
        _parsed(primary_intent="documentation_request", needs_documentation=True),
        history,
        [],
    )
    assert agent.turn_resolution.turn_type in {"fresh_request", "new_request"}
    assert agent.turn_resolution.should_reuse_active_entity is False


def test_active_business_line_is_persisted_into_session_payload():
    history = _history_with_route_state({"active_route": "commercial_agent", "route_phase": "active"})
    agent = build_agent_input(
        "t12",
        "brochure for car-t",
        _parsed(primary_intent="documentation_request", needs_documentation=True),
        history,
        [],
    )
    assert agent.session_payload.active_business_line == "car_t"


def test_reference_resolution_can_match_by_display_name():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "route_phase": "active",
            "session_payload": {
                "recent_entities": [
                    {
                        "identifier": "CS-4",
                        "identifier_type": "",
                        "entity_kind": "service",
                        "display_name": "Baculovirus Expression",
                        "business_line": "other_service",
                    }
                ],
            },
        }
    )
    agent = build_agent_input("t13", "tell me more about baculovirus expression", _parsed(primary_intent="follow_up"), history, [])
    assert agent.reference_resolution.resolved_display_name == "Baculovirus Expression"


def test_active_service_context_is_preserved_across_follow_up_turns():
    history = _history_with_route_state(
        {
            "active_route": "workflow_agent",
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
                "active_target": "EGFP mRNA",
                "active_business_line": "mrna_lnp",
                "last_user_goal": "request_technical_information",
            },
        }
    )
    agent = build_agent_input("t14", "what models do you support?", _parsed(primary_intent="follow_up"), history, [])
    assert agent.active_service_name == "mRNA-LNP Gene Delivery"
    assert agent.active_business_line == "mrna_lnp"
    assert agent.active_target == "EGFP mRNA"
    assert agent.session_payload.active_service_name == "mRNA-LNP Gene Delivery"
    assert agent.session_payload.active_target == "EGFP mRNA"


def test_explicit_service_turn_does_not_pollute_product_context():
    agent = build_agent_input(
        "t14b",
        "Tell me about mRNA-LNP Gene Delivery",
        _parsed(primary_intent="general_info", service_names=["mRNA-LNP Gene Delivery"]),
        [],
        [],
    )
    assert agent.active_service_name == "mRNA-LNP Gene Delivery"
    assert agent.active_product_name == ""
    assert agent.session_payload.active_entity.entity_kind == "service"
    assert agent.session_payload.active_entity.identifier == ""
    assert agent.session_payload.active_entity.identifier_type == ""
    assert agent.effective_query == "Tell me about mRNA-LNP Gene Delivery"
    assert agent.retrieval_query == "Tell me about mRNA-LNP Gene Delivery"


def test_current_turn_product_and_target_are_promoted_into_active_context():
    agent = build_agent_input(
        "t15",
        "tell me about mouse monoclonal antibody to nucleophosmin",
        _parsed(
            primary_intent="product_inquiry",
            product_names=["Mouse Monoclonal antibody to Nucleophosmin"],
            targets=["Nucleophosmin"],
        ),
        [],
        [],
    )
    assert agent.active_product_name == "Mouse Monoclonal antibody to Nucleophosmin"
    assert agent.active_target == "Nucleophosmin"
    assert agent.session_payload.active_product_name == "Mouse Monoclonal antibody to Nucleophosmin"
    assert agent.session_payload.active_target == "Nucleophosmin"


def test_explicit_new_service_replaces_previous_active_service_context():
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
        "t16",
        "tell me about Custom CAR-NK Manufacturing",
        _parsed(primary_intent="general_info", service_names=["Custom CAR-NK Manufacturing"]),
        history,
        [],
    )
    assert agent.active_service_name == "Custom CAR-NK Manufacturing"
    assert agent.session_payload.active_service_name == "Custom CAR-NK Manufacturing"
