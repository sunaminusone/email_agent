from __future__ import annotations

from typing import Any

from src.schemas import RouteDecision

from .route_policy_shared import (
    finalize_decision,
    has_catalog_reference,
    is_deep_technical_request,
    is_intro_style_request,
    join_values,
)


def resolve_technical_route(
    agent_input: dict[str, Any],
    *,
    intent: str,
    request_flags: dict[str, Any],
    missing_information: list[str],
    business_line: str,
    engagement_type: str,
    product_names: list[str],
    catalog_numbers: list[str],
    gray_zone_reasons: list[str],
) -> RouteDecision | None:
    if (
        has_catalog_reference(agent_input)
        and is_intro_style_request(agent_input)
        and not request_flags.get("needs_price")
        and not request_flags.get("needs_quote")
        and not request_flags.get("needs_documentation")
        and not request_flags.get("needs_order_status")
        and not request_flags.get("needs_shipping_info")
        and not is_deep_technical_request(agent_input)
    ):
        product_reference = join_values(catalog_numbers) or join_values(product_names) or "the requested product"
        return finalize_decision(RouteDecision(
            route_name="commercial_agent",
            business_line=business_line,
            engagement_type="catalog_product",
            route_confidence=0.95,
            business_goal=f"Introduce {product_reference} using catalog facts and supporting technical context",
            reason="The message asks for an introduction or overview of a referenced product-like entity, so catalog facts should lead and technical retrieval can supplement.",
            required_capabilities=["commercial_tool_selection", "product_lookup", "technical_retrieval"],
            recommended_next_steps=[
                "Match the requested product or alias in the catalog",
                "Supplement the product summary with relevant technical context when available",
                "Prepare a concise product introduction grounded in retrieved facts",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=True,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    if intent in {"technical_question", "troubleshooting"} and missing_information:
        return finalize_decision(RouteDecision(
            route_name="clarification_request",
            business_line=business_line,
            engagement_type=engagement_type,
            route_confidence=0.94,
            business_goal="Collect the minimum experiment details required for a reliable biotech response",
            reason="The request is technical but important details are still missing.",
            required_capabilities=["clarification_generation"],
            recommended_next_steps=[
                "Ask targeted follow-up questions",
                "Delay technical recommendations until the missing details are collected",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=False,
            should_escalate_to_human=False,
        ), agent_input)

    if intent in {"technical_question", "troubleshooting"}:
        return finalize_decision(RouteDecision(
            route_name="commercial_agent",
            business_line=business_line,
            engagement_type="general_inquiry" if engagement_type == "custom_service" and gray_zone_reasons else engagement_type,
            route_confidence=0.92 if not gray_zone_reasons else 0.78,
            business_goal="Retrieve technical knowledge and prepare a scientifically grounded response",
            reason="The parsed input is primarily a technical or troubleshooting request.",
            required_capabilities=["commercial_tool_selection", "technical_retrieval", "scientific_reasoning"],
            recommended_next_steps=[
                "Retrieve the most relevant technical knowledge",
                "Draft a technical response grounded in the available evidence",
            ],
            missing_information_to_request=[],
            should_write_draft=True,
            should_retrieve_knowledge=True,
            should_call_tools=False,
            should_escalate_to_human=False,
        ), agent_input)

    return None


def resolve_commercial_route(
    agent_input: dict[str, Any],
    *,
    intent: str,
    request_flags: dict[str, Any],
    missing_information: list[str],
    business_line: str,
    engagement_type: str,
    product_names: list[str],
    catalog_numbers: list[str],
    destination: str | None,
    needs_timeline: Any,
) -> RouteDecision | None:
    if request_flags.get("needs_quote") or request_flags.get("needs_price") or intent == "pricing_question":
        product_reference = join_values(catalog_numbers) or join_values(product_names) or "the requested product"
        business_goal = f"Retrieve commercial data for {product_reference}"
        reason = "The input is a pricing or quotation request."
        next_steps = [
            "Match the product or catalog number",
            "Check price and availability",
        ]

        if needs_timeline and destination:
            business_goal += f" and confirm lead time for shipments to {destination}"
            reason = f"The input is a pricing request for {product_reference} and also asks for lead time to {destination}."
            next_steps.append(f"Check lead time for shipments to {destination}")
        elif needs_timeline:
            business_goal += " and confirm the expected lead time"
            reason = f"The input is a pricing request for {product_reference} and also asks for lead time."
            next_steps.append("Check the expected lead time")
        elif destination:
            business_goal += f" with destination-specific handling for {destination}"
            reason = f"The input is a pricing request for {product_reference} with a destination constraint for {destination}."
            next_steps.append(f"Check whether destination-specific commercial or logistics constraints apply to {destination}")

        next_steps.append("Prepare a sales-ready draft response")
        return finalize_decision(RouteDecision(
            route_name="commercial_agent",
            business_line=business_line,
            engagement_type="catalog_product",
            route_confidence=0.97,
            business_goal=business_goal,
            reason=reason,
            required_capabilities=["commercial_tool_selection", "product_lookup", "quote_support"],
            recommended_next_steps=next_steps,
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    if request_flags.get("needs_documentation") or intent == "documentation_request":
        product_lookup_keys = agent_input.get("product_lookup_keys", {})
        service_names = product_lookup_keys.get("service_names", [])
        document_names = agent_input.get("entities", {}).get("document_names", [])
        has_specific_document_scope = bool(
            catalog_numbers
            or product_names
            or service_names
            or business_line not in {"", "unknown"}
        )
        if not has_specific_document_scope:
            document_label = "/".join(document_names) if document_names else "documentation"
            question = (
                f"Please confirm which business line you need the {document_label} for: Antibody, CAR-T/CAR-NK, mRNA-LNP, or Other Service."
            )
            return finalize_decision(RouteDecision(
                route_name="clarification_request",
                business_line=business_line,
                engagement_type=engagement_type,
                route_confidence=0.95,
                business_goal="Clarify the target business line before retrieving general brochures or flyers",
                reason="The request asks for documentation, but no product reference or business line was provided.",
                required_capabilities=["clarification_generation"],
                recommended_next_steps=[
                    "Ask which business line or product family the user wants documentation for",
                    "Delay document retrieval until the target scope is confirmed",
                ],
                missing_information_to_request=[question],
                should_write_draft=True,
                should_retrieve_knowledge=False,
                should_call_tools=False,
                should_escalate_to_human=False,
            ), agent_input)
        return finalize_decision(RouteDecision(
            route_name="commercial_agent",
            business_line=business_line,
            engagement_type=engagement_type,
            route_confidence=0.96,
            business_goal="Retrieve the requested biotech documentation and prepare a response",
            reason="The message is asking for documents or technical files.",
            required_capabilities=["commercial_tool_selection", "document_lookup"],
            recommended_next_steps=[
                "Identify the requested file type",
                "Retrieve the matching product documentation",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=True,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    if request_flags.get("needs_availability") or intent == "product_inquiry":
        product_reference = join_values(catalog_numbers) or join_values(product_names) or "the requested product"
        return finalize_decision(RouteDecision(
            route_name="commercial_agent",
            business_line=business_line,
            engagement_type="catalog_product",
            route_confidence=0.93,
            business_goal=f"Match {product_reference} to the best-fit catalog offering",
            reason="The message is asking about an existing product or availability without a direct pricing request.",
            required_capabilities=["commercial_tool_selection", "product_lookup"],
            recommended_next_steps=[
                "Match the product name, target, or catalog number",
                "Check whether a standard catalog product exists",
                "Prepare a product-oriented response",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    return None
