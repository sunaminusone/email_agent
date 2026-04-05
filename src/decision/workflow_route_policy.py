from __future__ import annotations

from typing import Any

from src.schemas import RouteDecision

from .route_policy_shared import finalize_decision, join_values


def resolve_workflow_route(
    agent_input: dict[str, Any],
    *,
    intent: str,
    request_flags: dict[str, Any],
    engagement_type: str,
    business_line: str,
    custom_signals: dict[str, Any],
    product_names: list[str],
    catalog_numbers: list[str],
    missing_information: list[str],
) -> RouteDecision | None:
    if request_flags.get("needs_customization") or intent == "customization_request" or engagement_type == "custom_service":
        product_reference = join_values(product_names) or join_values(catalog_numbers) or "the requested solution"
        matched_signals = (
            custom_signals["strong_phrases"]
            + custom_signals["action_strong"]
            + custom_signals["action_weak"]
            + custom_signals["object_strong"]
            + custom_signals["object_weak"]
        )
        signal_summary = ", ".join(matched_signals[:4])
        reason = (
            f"The message is asking for a custom or tailored solution around {product_reference}."
            if product_reference != "the requested solution"
            else "The message is asking for a custom or tailored solution rather than a standard catalog item."
        )
        if signal_summary and not request_flags.get("needs_customization") and intent != "customization_request":
            reason = f"{reason[:-1]} Signals matched: {signal_summary}."
        return finalize_decision(RouteDecision(
            route_name="workflow_agent",
            business_line=business_line,
            engagement_type="custom_service",
            route_confidence=0.96,
            business_goal=f"Qualify the custom {business_line.replace('_', '-')} request and collect the specifications needed for project scoping" if business_line != "unknown" else "Qualify the customization request and collect the specifications needed for project scoping",
            reason=reason,
            required_capabilities=["workflow_state_management", "custom_intake", "business_review"],
            recommended_next_steps=[
                "Identify the target product family and desired outcome",
                "Collect the core technical and commercial specifications",
                "Prepare an internally aligned response or handoff for project scoping",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=True,
            should_escalate_to_human=False,
        ), agent_input)

    return None
