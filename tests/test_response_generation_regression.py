from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
from src.conversation.agent_input_service import build_agent_input
from src.decision import route_agent_input
from src.decision.response_resolution import resolve_response
from src.decision.response_service import build_response_artifacts, generate_final_response
from src.response import chain as response_chain


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
    product_names: list[str] | None = None,
    catalog_numbers: list[str] | None = None,
    service_names: list[str] | None = None,
    targets: list[str] | None = None,
    needs_documentation: bool = False,
    needs_timeline: bool = False,
    needs_price: bool = False,
    needs_quote: bool = False,
    referenced_prior_context: str | None = None,
):
    return ParsedResult(
        context=ParsedContext(primary_intent=primary_intent),
        entities=Entities(
            product_names=list(product_names or []),
            catalog_numbers=list(catalog_numbers or []),
            service_names=list(service_names or []),
            targets=list(targets or []),
        ),
        request_flags=RequestFlags(
            needs_documentation=needs_documentation,
            needs_timeline=needs_timeline,
            needs_price=needs_price,
            needs_quote=needs_quote,
        ),
        open_slots=OpenSlots(referenced_prior_context=referenced_prior_context),
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
        "catalog_no": "20001",
        "name": "Mouse Monoclonal antibody to Nucleophosmin",
        "display_name": "Mouse Monoclonal antibody to Nucleophosmin",
        "business_line": "Antibody",
        "target_antigen": "Nucleophosmin",
        "application_text": "Western blot; IHC",
        "species_reactivity_text": "Human, Mouse",
        "price_text": "$199",
        "lead_time_text": "5-7 business days",
        "currency": "USD",
        "matched_field": "catalog_no",
        "match_rank": 200,
    }


def test_commercial_route_prefers_pricing_responder_for_lead_time_follow_up():
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
            },
        }
    )
    agent = build_agent_input(
        "lead-time-thread",
        "what about the lead time?",
        _parsed(primary_intent="follow_up", needs_timeline=True),
        history,
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Check lead time",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={"matches": [_product_match()]},
            ),
            ExecutedAction(
                action_id="price",
                action_type="lookup_price",
                status="completed",
                output={"matches": [_product_match()]},
            ),
            ExecutedAction(
                action_id="draft",
                action_type="draft_reply",
                status="completed",
                output={},
            ),
        ],
    )
    response = generate_final_response(RuntimeContext(agent_context=agent), _route(), execution_run)
    assert "lead time" in response.message.lower()
    assert "commercial agent lookup" not in response.message.lower()
    assert "price for" not in response.message.lower()
    assert response.message.startswith("The current expected lead time for")
    assert response.grounded_action_types == ["lookup_price"]
    resolution = resolve_response(agent, _route(), execution_run)
    assert resolution.answer_focus == "lead_time"
    assert resolution.preferred_route_name == "pricing_lookup"
    assert resolution.include_lead_time is True
    assert resolution.include_price is False
    assert resolution.content_priority[:2] == ["lead_time", "product_identity"]
    artifacts = build_response_artifacts(RuntimeContext(agent_context=agent), _route(), execution_run)
    assert artifacts["response_path"] == "renderer"
    assert artifacts["legacy_fallback_used"] is False
    assert artifacts["legacy_fallback_reason"] == "disabled_for_topic:commercial_quote"


def test_commercial_route_prefers_documentation_responder_for_document_request():
    agent = build_agent_input(
        "doc-thread",
        "brochure for car-t",
        _parsed(primary_intent="documentation_request", needs_documentation=True),
        [],
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Retrieve brochure",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={"matches": [{"catalog_no": "PM-CAR1000", "name": "Mock CD28 CAR-T", "business_line": "CAR-T/CAR-NK"}]},
            ),
            ExecutedAction(
                action_id="doc",
                action_type="lookup_document",
                status="completed",
                output={
                    "requested_document_types": ["brochure"],
                    "matches": [
                        {
                            "file_name": "Brochure_CAR-T Products.pdf",
                            "product_scope": "business_line",
                            "document_url": "/documents/Brochure_CAR-T%20Products.pdf",
                        }
                    ],
                },
            ),
            ExecutedAction(
                action_id="draft",
                action_type="draft_reply",
                status="completed",
                output={},
            ),
        ],
    )
    response = generate_final_response(RuntimeContext(agent_context=agent), _route(business_line="car_t"), execution_run)
    assert "brochure_car-t products.pdf".lower() in response.message.lower()
    assert "commercial agent lookup" not in response.message.lower()
    assert response.message.startswith("I found a strong document match you can share:")
    assert response.grounded_action_types == ["lookup_document"]
    resolution = resolve_response(agent, _route(business_line="car_t"), execution_run)
    assert resolution.answer_focus == "documentation"
    assert resolution.preferred_route_name == "documentation_lookup"
    assert resolution.reply_style == "sales"
    assert resolution.content_priority[:2] == ["documents", "product_identity"]


def test_pricing_renderer_handles_unavailable_price_without_falling_back_to_llm():
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
            },
        }
    )
    product_match = _product_match()
    product_match.pop("price_text", None)
    product_match.pop("price", None)

    agent = build_agent_input(
        "price-unavailable-thread",
        "what about the price?",
        _parsed(primary_intent="follow_up", needs_price=True),
        history,
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Check price",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={"matches": [product_match]},
            ),
            ExecutedAction(
                action_id="price",
                action_type="lookup_price",
                status="not_found",
                output={"matches": [], "match_status": "not_found"},
            ),
        ],
    )
    artifacts = build_response_artifacts(RuntimeContext(agent_context=agent), _route(), execution_run)
    assert artifacts["response_path"] == "renderer"
    assert artifacts["legacy_fallback_used"] is False
    assert "does not include pricing" in artifacts["final_response"].message.lower()
    assert "latest commercial quote" in artifacts["final_response"].message.lower()


def test_pricing_renderer_handles_unavailable_lead_time_without_falling_back_to_llm():
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
            },
        }
    )
    product_match = _product_match()
    product_match.pop("lead_time_text", None)

    agent = build_agent_input(
        "lead-unavailable-thread",
        "what about the lead time?",
        _parsed(primary_intent="follow_up", needs_timeline=True),
        history,
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Check lead time",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={"matches": [product_match]},
            ),
            ExecutedAction(
                action_id="price",
                action_type="lookup_price",
                status="not_found",
                output={"matches": [], "match_status": "not_found"},
            ),
        ],
    )
    artifacts = build_response_artifacts(RuntimeContext(agent_context=agent), _route(), execution_run)
    assert artifacts["response_path"] == "renderer"
    assert artifacts["legacy_fallback_used"] is False
    assert "does not include a confirmed lead time" in artifacts["final_response"].message.lower()
    assert "latest delivery window" in artifacts["final_response"].message.lower()


def test_document_renderer_handles_not_found_document_without_falling_back_to_llm():
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
            },
        }
    )
    agent = build_agent_input(
        "doc-not-found-thread",
        "can you send the brochure?",
        _parsed(primary_intent="documentation_request", needs_documentation=True),
        history,
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Retrieve brochure",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={"matches": [_product_match()]},
            ),
            ExecutedAction(
                action_id="doc",
                action_type="lookup_document",
                status="not_found",
                output={"requested_document_types": ["brochure"], "matches": [], "documents_found": 0},
            ),
        ],
    )
    artifacts = build_response_artifacts(RuntimeContext(agent_context=agent), _route(), execution_run)
    assert artifacts["response_path"] == "renderer"
    assert artifacts["legacy_fallback_used"] is False
    assert "couldn't find a brochure specifically for 20001" in artifacts["final_response"].message.lower()
    assert "closest product-line material" in artifacts["final_response"].message.lower()


def test_response_pipeline_marks_legacy_fallback_when_renderer_is_unavailable(monkeypatch):
    def _force_legacy(_payload):
        raise response_chain.RendererUnavailableError("forced fallback for regression test")

    monkeypatch.setattr(response_chain, "render_topic_response", _force_legacy)

    chain_output = response_chain._run_topic_chain(
        {
            "topic_type": "commercial_quote",
            "legacy_fallback_response": response_chain.FinalResponse(
                message="Legacy fallback reply",
                response_type="answer",
            ),
            "legacy_fallback_route": "commercial_agent",
            "legacy_fallback_responder": "CommercialResponder",
            "legacy_fallback_reason": "forced_for_test",
        }
    )
    assert chain_output["response_path"] == "legacy_fallback"
    assert chain_output["legacy_fallback_used"] is True
    assert chain_output["legacy_fallback_route"] == "commercial_agent"
    assert chain_output["legacy_fallback_responder"] == "CommercialResponder"
    assert chain_output["legacy_fallback_reason"] == "forced_for_test"


def test_product_follow_up_other_information_is_not_reduced_to_best_match():
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
            },
        }
    )
    agent = build_agent_input(
        "info-thread",
        "can you provide other information?",
        _parsed(primary_intent="follow_up"),
        history,
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Provide product information",
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
    response = generate_final_response(RuntimeContext(agent_context=agent), _route("product_lookup"), execution_run)
    assert "additional information" in response.message.lower()
    assert "best product match" not in response.message.lower()
    assert "target antigen" in response.message.lower()
    assert "applications include" in response.message.lower()
    assert "species reactivity" in response.message.lower()


def test_product_detail_question_selects_detail_fields_without_price_by_default():
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
            },
        }
    )
    agent = build_agent_input(
        "detail-thread",
        "can you tell me more details about it?",
        _parsed(primary_intent="follow_up"),
        history,
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Provide product details",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={"matches": [_product_match()]},
            ),
            ExecutedAction(
                action_id="price",
                action_type="lookup_price",
                status="completed",
                output={"matches": [_product_match()]},
            ),
        ],
    )
    resolution = resolve_response(agent, _route("commercial_agent"), execution_run)
    assert resolution.answer_focus == "product_elaboration"
    assert resolution.include_target_antigen is True
    assert resolution.include_application is True
    assert resolution.include_species_reactivity is True
    assert resolution.include_price is False
    assert resolution.content_priority[:4] == ["product_identity", "target_antigen", "application", "species_reactivity"]
    response = generate_final_response(RuntimeContext(agent_context=agent), _route("commercial_agent"), execution_run)
    assert response.message.startswith("Here is some additional information")
    assert "target antigen" in response.message.lower()
    assert "applications include" in response.message.lower()
    assert "species reactivity" in response.message.lower()
    assert "listed price" not in response.message.lower()


def test_customer_friendly_document_request_uses_customer_friendly_style():
    agent = build_agent_input(
        "doc-style-thread",
        "can you share a customer-friendly brochure for car-t?",
        _parsed(primary_intent="documentation_request", needs_documentation=True),
        [],
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Retrieve brochure",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="doc",
                action_type="lookup_document",
                status="completed",
                output={
                    "requested_document_types": ["brochure"],
                    "matches": [
                        {
                            "file_name": "Brochure_CAR-T Products.pdf",
                            "product_scope": "business_line",
                            "document_url": "/documents/Brochure_CAR-T%20Products.pdf",
                        }
                    ],
                },
            )
        ],
    )
    resolution = resolve_response(agent, _route(business_line="car_t"), execution_run)
    assert resolution.reply_style == "customer_friendly"
    response = generate_final_response(RuntimeContext(agent_context=agent), _route(business_line="car_t"), execution_run)
    assert "document you can share directly" in response.message.lower()


def test_technical_query_uses_technical_style():
    agent = build_agent_input(
        "tech-style-thread",
        "can you give me a technical explanation of this validation result?",
        _parsed(primary_intent="technical_question"),
        [],
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Retrieve technical evidence",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="tech",
                action_type="retrieve_technical_knowledge",
                status="completed",
                output={
                    "matches": [
                        {
                            "file_name": "Validation Note.pdf",
                            "content_preview": "This validation result supports strong staining in western blot under reducing conditions.",
                        }
                    ]
                },
            )
        ],
    )
    resolution = resolve_response(agent, _route("technical_rag"), execution_run)
    assert resolution.reply_style == "technical"
    response = generate_final_response(RuntimeContext(agent_context=agent), _route("technical_rag"), execution_run)
    assert "mouse monoclonal antibodies" in response.message.lower()
    assert "timeline" in response.message.lower()


def test_technical_renderer_acknowledges_active_service_scope():
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
        "tech-scope-thread",
        "What is the service plan?",
        _parsed(primary_intent="follow_up"),
        history,
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Retrieve technical evidence",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="tech",
                action_type="retrieve_technical_knowledge",
                status="completed",
                output={
                    "business_line_hint": "mrna_lnp",
                    "matches": [
                        {
                            "file_name": "promab_mrna_lnp_gene_delivery_rag_ready.txt",
                            "chunk_label": "Discovery Services Plan - Phase I",
                            "content_preview": "Discovery Services Plan is a phased plan with three main phases followed by two optional phases.",
                        }
                    ],
                    "retrieval_debug": {
                        "effective_scope_type": "service",
                        "effective_scope_name": "mRNA-LNP Gene Delivery",
                        "effective_scope_source": "active",
                        "acknowledgement_mode": "assumed",
                    },
                },
            )
        ],
    )
    response = generate_final_response(RuntimeContext(agent_context=agent), _route("technical_rag", business_line="mrna_lnp"), execution_run)
    assert "previously discussed mrna-lnp gene delivery service" in response.message.lower()
    assert "mrna-lnp gene delivery" in response.message.lower()


def test_product_renderer_acknowledges_service_to_product_switch():
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
            },
        }
    )
    agent = build_agent_input(
        "product-switch-thread",
        "Tell me about PM-LNP-1001",
        _parsed(primary_intent="product_inquiry", product_names=["mRNA-LNP Starter Kit"], catalog_numbers=["PM-LNP-1001"]),
        history,
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Provide product details",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={
                    "matches": [
                        {
                            "catalog_no": "PM-LNP-1001",
                            "name": "mRNA-LNP Starter Kit",
                            "business_line": "mRNA-LNP",
                            "target_antigen": "EGFP mRNA",
                        }
                    ]
                },
            )
        ],
    )
    response = generate_final_response(RuntimeContext(agent_context=agent), _route("product_lookup", business_line="mrna_lnp"), execution_run)
    assert "mRNA-lnp starter kit".lower() in response.message.lower()
    assert "egfp mrna" in response.message.lower()


def test_workflow_route_uses_workflow_renderer_for_missing_information():
    agent = build_agent_input(
        "workflow-thread",
        "I need a custom CAR-T service",
        _parsed(primary_intent="customization_request"),
        [],
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Prepare workflow intake",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="workflow",
                action_type="prepare_customization_intake",
                status="completed",
                output={
                    "workflow_mode": "customization_intake",
                    "business_line": "car_t",
                    "missing_information": ["target", "species", "project scope"],
                },
            )
        ],
    )
    response = generate_final_response(RuntimeContext(agent_context=agent), _route("workflow_agent", business_line="car_t"), execution_run)
    assert response.response_type == "clarification"
    assert "workflow intake stage" in response.message.lower()
    assert "car_t customization request" in response.message.lower()
    assert "target; species; project scope" in response.message.lower()


def test_operational_invoice_topic_uses_operational_renderer():
    agent = build_agent_input(
        "invoice-thread",
        "invoice 54321",
        _parsed(primary_intent="order_support"),
        [],
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Lookup invoice",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="invoice",
                action_type="lookup_invoice",
                status="completed",
                output={
                    "invoice_status": "completed",
                    "matches": [
                        {
                            "doc_number": "54321",
                            "customer_name": "ABC Bio",
                            "txn_date": "2026-03-18",
                            "due_date": "2026-04-18",
                            "total_amt": "1200.00",
                            "balance": "450.00",
                            "raw": {
                                "BillAddr": {
                                    "Line1": "1 Main St",
                                    "City": "San Diego",
                                    "CountrySubDivisionCode": "CA",
                                    "PostalCode": "92101",
                                    "Country": "USA",
                                }
                            },
                        }
                    ],
                },
            )
        ],
    )
    response = generate_final_response(RuntimeContext(agent_context=agent), _route("operational_agent", business_line="unknown"), execution_run)
    assert response.response_type == "answer"
    assert "quickbooks invoice record" in response.message.lower()
    assert "invoice number: 54321" in response.message.lower()
    assert "customer: abc bio" in response.message.lower()


def test_product_renderer_handles_multiple_product_identity_blocks():
    agent = build_agent_input(
        "multi-product-thread",
        "what about both of them?",
        _parsed(primary_intent="follow_up"),
        [],
        [],
    )
    execution_run = ExecutionRun(
        plan_goal="Summarize multiple products",
        overall_status="completed",
        executed_actions=[
            ExecutedAction(
                action_id="product",
                action_type="lookup_catalog_product",
                status="completed",
                output={
                    "matches": [
                        {
                            "catalog_no": "20001",
                            "name": "Mouse Monoclonal antibody to Nucleophosmin",
                            "business_line": "Antibody",
                        },
                        {
                            "catalog_no": "20002",
                            "name": "Rabbit Monoclonal antibody to TP53",
                            "business_line": "Antibody",
                        },
                    ]
                },
            )
        ],
    )
    response = generate_final_response(RuntimeContext(agent_context=agent), _route(), execution_run)
    assert response.response_type == "answer"
    assert "multiple products" in response.message.lower()
    assert "20001" in response.message
    assert "20002" in response.message


def test_broad_service_capability_question_without_active_service_requests_clarification():
    agent = build_agent_input(
        "service-scope-thread-1",
        "What models do you support?",
        _parsed(primary_intent="technical_question"),
        [],
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name == "clarification_request"
    assert routed.route.missing_information_to_request
    assert "which service" in routed.route.missing_information_to_request[0].lower()


def test_broad_service_capability_question_with_active_service_keeps_follow_up_route():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "mrna_lnp",
            "active_engagement_type": "custom_service",
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
        "service-scope-thread-2",
        "What models do you support?",
        _parsed(primary_intent="follow_up"),
        history,
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name != "clarification_request"


def test_broad_service_plan_question_without_active_service_requests_clarification():
    agent = build_agent_input(
        "service-scope-thread-3",
        "What is your service plan?",
        _parsed(primary_intent="technical_question"),
        [],
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name == "clarification_request"
    assert routed.route.missing_information_to_request
    assert "which service" in routed.route.missing_information_to_request[0].lower()


def test_broad_service_plan_question_with_active_service_keeps_follow_up_route():
    history = _history_with_route_state(
        {
            "active_route": "commercial_agent",
            "active_business_line": "antibody",
            "active_engagement_type": "custom_service",
            "route_phase": "active",
            "session_payload": {
                "active_entity": {
                    "identifier": "",
                    "identifier_type": "",
                    "entity_kind": "service",
                    "display_name": "Mouse Monoclonal Antibodies",
                    "business_line": "antibody",
                },
                "active_service_name": "Mouse Monoclonal Antibodies",
                "active_business_line": "antibody",
                "last_user_goal": "request_service_plan",
            },
        }
    )
    agent = build_agent_input(
        "service-scope-thread-4",
        "What is your service plan?",
        _parsed(primary_intent="follow_up"),
        history,
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name != "clarification_request"


def test_referential_antibody_question_without_active_scope_requests_clarification():
    agent = build_agent_input(
        "referential-scope-thread-1",
        "What applications is this antibody validated for?",
        _parsed(
            primary_intent="technical_question",
            referenced_prior_context="this antibody",
        ),
        [],
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name == "clarification_request"
    assert routed.route.missing_information_to_request
    assert "which antibody or product" in routed.route.missing_information_to_request[0].lower()


def test_referential_antibody_question_with_active_product_skips_clarification():
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
                "active_product_name": "Mouse Monoclonal antibody to Nucleophosmin",
                "active_business_line": "antibody",
                "last_user_goal": "request_product_information",
            },
        }
    )
    agent = build_agent_input(
        "referential-scope-thread-2",
        "What applications is this antibody validated for?",
        _parsed(
            primary_intent="technical_question",
            referenced_prior_context="this antibody",
        ),
        history,
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name != "clarification_request"


def test_ambiguous_product_alias_requests_clarification_with_all_candidates():
    agent = build_agent_input(
        "ambiguous-alias-thread-1",
        "Tell me about MSH2",
        _parsed(primary_intent="product_inquiry", product_names=["MSH2"]),
        [],
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name == "clarification_request"
    assert routed.route.missing_information_to_request
    message = routed.route.missing_information_to_request[0]
    assert 'multiple products matching "MSH2"' in message
    assert "20025" in message
    assert "P06329" in message
    assert "reply with the catalog number" in message.lower()


def test_unique_product_alias_does_not_trigger_ambiguous_alias_clarification():
    agent = build_agent_input(
        "ambiguous-alias-thread-2",
        "Tell me about NPM1",
        _parsed(primary_intent="product_inquiry", product_names=["Mouse Monoclonal antibody to Nucleophosmin"]),
        [],
        [],
    )

    routed = route_agent_input(RuntimeContext(agent_context=agent))

    assert routed.route.route_name != "clarification_request"


def test_ambiguous_product_alias_clarification_response_preserves_candidate_list():
    agent = build_agent_input(
        "ambiguous-alias-thread-3",
        "Tell me about MSH2",
        _parsed(primary_intent="product_inquiry", product_names=["MSH2"]),
        [],
        [],
    )
    routed = route_agent_input(RuntimeContext(agent_context=agent))
    execution_run = ExecutionRun(
        plan_goal="Clarify ambiguous product alias",
        overall_status="completed",
        executed_actions=[],
    )

    response = generate_final_response(
        RuntimeContext(agent_context=agent),
        routed.route,
        execution_run,
    )

    assert response.response_type == "clarification"
    assert 'multiple products matching "MSH2"' in response.message
    assert "20025" in response.message
    assert "P06329" in response.message
