from __future__ import annotations

from typing import Any

from src.schemas import RouteDecision

from .route_policy_shared import (
    finalize_decision,
    is_customer_lookup_request,
    is_invoice_lookup_request,
    join_values,
)


def resolve_operational_route(
    agent_input: dict[str, Any],
    *,
    intent: str,
    request_flags: dict[str, Any],
    missing_information: list[str],
    business_line: str,
    engagement_type: str,
) -> RouteDecision | None:
    if is_customer_lookup_request(agent_input):
        customer_reference = join_values(agent_input.get("entities", {}).get("company_names", [])) or "the requested customer"
        return finalize_decision(RouteDecision(
            route_name="operational_agent",
            business_line=business_line,
            engagement_type="general_inquiry",
            route_confidence=0.94,
            business_goal=f"Retrieve the customer or lead profile for {customer_reference}",
            reason="The message is asking for customer or lead contact details from QuickBooks.",
            required_capabilities=["operational_tool_selection", "customer_lookup"],
            recommended_next_steps=[
                "Verify the customer or company name",
                "Retrieve phone, email, address, and open balance details",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    if is_invoice_lookup_request(agent_input):
        invoice_reference = (
            join_values(agent_input.get("entities", {}).get("order_numbers", []))
            or join_values(agent_input.get("entities", {}).get("company_names", []))
            or "the requested invoice"
        )
        return finalize_decision(RouteDecision(
            route_name="operational_agent",
            business_line=business_line,
            engagement_type="general_inquiry",
            route_confidence=0.96,
            business_goal=f"Retrieve the QuickBooks invoice details for {invoice_reference}",
            reason="The parsed input is specifically asking about an invoice or billing record.",
            required_capabilities=["operational_tool_selection", "invoice_lookup"],
            recommended_next_steps=[
                "Verify the invoice identifier or customer name",
                "Retrieve invoice amount, balance, due date, and status details",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    if request_flags.get("needs_order_status") or intent == "order_support":
        return finalize_decision(RouteDecision(
            route_name="operational_agent",
            business_line=business_line,
            engagement_type=engagement_type,
            route_confidence=0.97,
            business_goal="Handle the order-related request using operational data",
            reason="The parsed input indicates an existing order or billing workflow.",
            required_capabilities=["operational_tool_selection", "order_lookup"],
            recommended_next_steps=[
                "Verify the order identifier",
                "Query the order or billing system",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    if request_flags.get("needs_shipping_info") or intent == "shipping_question":
        return finalize_decision(RouteDecision(
            route_name="operational_agent",
            business_line=business_line,
            engagement_type=engagement_type,
            route_confidence=0.95,
            business_goal="Resolve the logistics question and draft a shipping-focused response",
            reason="The parsed input indicates a shipping or delivery workflow.",
            required_capabilities=["operational_tool_selection", "shipping_lookup"],
            recommended_next_steps=[
                "Check destination-specific shipping constraints",
                "Provide logistics or ETA guidance",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    return None
