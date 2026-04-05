from __future__ import annotations

from typing import Any

from src.schemas import RouteDecision
from src.strategies import detect_business_line, detect_engagement_type

from .route_policy_shared import (
    finalize_decision,
    route_defaults_for_continuity,
)


def make_continuity_decision(agent_input: dict[str, Any], route_name: str, reason: str) -> RouteDecision:
    business_line = detect_business_line(agent_input)
    engagement_type = detect_engagement_type(agent_input, business_line)
    defaults = route_defaults_for_continuity(route_name)
    return finalize_decision(RouteDecision(
        route_name=route_name,
        business_line=business_line,
        engagement_type=engagement_type,
        route_confidence=0.9,
        business_goal=defaults["business_goal"],
        reason=reason,
        required_capabilities=defaults["required_capabilities"],
        recommended_next_steps=[
            "Preserve the active workflow context from the previous turn",
            "Use the newly supplied user details to continue the same handling path",
        ],
        missing_information_to_request=[],
        should_write_draft=True,
        should_retrieve_knowledge=defaults["should_retrieve_knowledge"],
        should_call_tools=defaults["should_call_tools"],
        should_escalate_to_human=route_name in {"complaint_review", "human_review"},
    ), agent_input)


def continuity_override(
    agent_input: dict[str, Any],
    *,
    context: dict[str, Any],
    risk_level: str,
    intent: str,
    request_flags: dict[str, Any],
    routing_memory: dict[str, Any],
) -> RouteDecision | None:
    strong_fresh_intent = (
        context.get("needs_human_review")
        or risk_level == "high"
        or intent in {"complaint", "partnership_request"}
        or request_flags.get("needs_quote")
        or request_flags.get("needs_price")
        or request_flags.get("needs_order_status")
        or request_flags.get("needs_invoice")
        or request_flags.get("needs_shipping_info")
        or request_flags.get("needs_documentation")
    )

    if (
        routing_memory.get("should_resume_pending_route")
        and routing_memory.get("pending_route_after_clarification")
        and not strong_fresh_intent
    ):
        return make_continuity_decision(
            agent_input,
            routing_memory["pending_route_after_clarification"],
            "The user appears to be replying to a clarification request, so the router resumes the pending business workflow.",
        )

    if (
        routing_memory.get("should_stick_to_active_route")
        and routing_memory.get("active_route") in {"commercial_agent", "operational_agent", "workflow_agent", "order_support", "complaint_review", "technical_rag"}
        and not strong_fresh_intent
        and intent in {"follow_up", "unknown", "general_info", "technical_question", "troubleshooting"}
    ):
        return make_continuity_decision(
            agent_input,
            routing_memory["active_route"],
            "The conversation appears to be continuing an active workflow, so the router keeps the existing route context.",
        )

    return None


def risk_or_handoff_override(
    agent_input: dict[str, Any],
    *,
    context: dict[str, Any],
    risk_level: str,
    intent: str,
    business_line: str,
    engagement_type: str,
) -> RouteDecision | None:
    if context.get("needs_human_review") or risk_level == "high":
        route_name = "complaint_review" if intent == "complaint" else "human_review"
        return finalize_decision(RouteDecision(
            route_name=route_name,
            business_line=business_line,
            engagement_type=engagement_type,
            route_confidence=0.98,
            business_goal="Escalate the message for safe manual handling",
            reason="The parsed input indicates elevated risk or explicit human review is needed.",
            required_capabilities=["manual_review"],
            recommended_next_steps=[
                "Flag the conversation for human handling",
                "Preserve parsed entities and urgency for the reviewer",
            ],
            missing_information_to_request=[],
            should_write_draft=False,
            should_retrieve_knowledge=False,
            should_call_tools=False,
            should_escalate_to_human=True,
        ), agent_input)

    if intent == "complaint":
        return finalize_decision(RouteDecision(
            route_name="complaint_review",
            business_line=business_line,
            engagement_type=engagement_type,
            route_confidence=0.95,
            business_goal="Handle the complaint carefully and prepare an internally reviewed response",
            reason="The primary intent is complaint handling.",
            required_capabilities=["manual_review", "case_summary"],
            recommended_next_steps=[
                "Summarize the complaint details",
                "Prepare a careful draft for internal review",
            ],
            missing_information_to_request=[],
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=False,
            should_escalate_to_human=True,
        ), agent_input)

    return None


def identifier_ambiguity_override(
    agent_input: dict[str, Any],
    *,
    business_line: str,
    engagement_type: str,
) -> RouteDecision | None:
    product_lookup_keys = agent_input.get("product_lookup_keys", {})
    ambiguous_identifiers = product_lookup_keys.get("ambiguous_identifiers", [])
    if not ambiguous_identifiers:
        return None

    if len(ambiguous_identifiers) == 1:
        question = (
            f"Please confirm whether {ambiguous_identifiers[0]} is a product/catalog number "
            "or an invoice/order number."
        )
    else:
        joined_identifiers = ", ".join(ambiguous_identifiers)
        question = (
            f"Please confirm whether these identifiers refer to product/catalog numbers "
            f"or invoice/order numbers: {joined_identifiers}."
        )

    return finalize_decision(RouteDecision(
        route_name="clarification_request",
        business_line=business_line,
        engagement_type=engagement_type,
        route_confidence=0.98,
        business_goal="Disambiguate the identifier type before continuing with product or operational lookup",
        reason="The message contains a numeric identifier that could refer to either a catalog product or a QuickBooks record.",
        required_capabilities=["clarification_generation"],
        recommended_next_steps=[
            "Ask whether the identifier is for a product/catalog item or an invoice/order record",
            "Resume the correct workflow after the user clarifies the identifier type",
        ],
        missing_information_to_request=[question],
        should_write_draft=True,
        should_retrieve_knowledge=False,
        should_call_tools=False,
        should_escalate_to_human=False,
    ), agent_input)
