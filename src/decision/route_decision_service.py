from __future__ import annotations

from typing import Any

from src.config.settings import get_llm
from src.context import build_routing_sections
from src.schemas import RouteDecision, RoutedRuntimeContext, RoutingDebugInfo, RuntimeContext
from src.strategies import (
    build_routing_debug_info as build_strategy_routing_debug_info,
    detect_business_line as detect_strategy_business_line,
    detect_engagement_type as detect_strategy_engagement_type,
    gray_zone_reasons as strategy_gray_zone_reasons,
    score_customization as strategy_score_customization,
)

from .commercial_route_policy import resolve_commercial_route, resolve_technical_route
from .operational_route_policy import resolve_operational_route
from .routing_prompt import get_routing_prompt
from .route_policy_shared import (
    combined_text,
    finalize_decision,
    safe_intent,
    safe_missing,
    safe_product_lookup_keys,
    safe_request_flags,
    safe_risk,
    safe_routing_memory,
)
from .route_preconditions import (
    continuity_override,
    identifier_ambiguity_override,
    risk_or_handoff_override,
)
from .workflow_route_policy import resolve_workflow_route


def _build_routing_chain():
    llm = get_llm()
    structured_llm = llm.with_structured_output(RouteDecision)
    routing_prompt = get_routing_prompt()
    return routing_prompt | structured_llm


def build_routing_debug_info(agent_input: dict[str, Any]) -> dict[str, Any]:
    return build_strategy_routing_debug_info(agent_input)


def _build_rule_override(agent_input: dict[str, Any]) -> RouteDecision | None:
    context = agent_input.get("context", {})
    intent = safe_intent(agent_input)
    risk_level = safe_risk(agent_input)
    missing_information = safe_missing(agent_input)
    request_flags = safe_request_flags(agent_input)
    routing_memory = safe_routing_memory(agent_input)
    product_lookup_keys = safe_product_lookup_keys(agent_input)
    product_names = product_lookup_keys.get("product_names", [])
    catalog_numbers = product_lookup_keys.get("catalog_numbers", [])
    destination = product_lookup_keys.get("destination")
    needs_timeline = product_lookup_keys.get("needs_timeline")
    business_line = detect_strategy_business_line(agent_input)
    engagement_type = detect_strategy_engagement_type(agent_input, business_line)
    custom_signals = strategy_score_customization(combined_text(agent_input))
    gray_zone_reasons = strategy_gray_zone_reasons(agent_input, business_line, engagement_type, custom_signals)

    continuity_decision = continuity_override(
        agent_input,
        context=context,
        risk_level=risk_level,
        intent=intent,
        request_flags=request_flags,
        routing_memory=routing_memory,
    )
    if continuity_decision is not None:
        return continuity_decision

    risk_decision = risk_or_handoff_override(
        agent_input,
        context=context,
        risk_level=risk_level,
        intent=intent,
        business_line=business_line,
        engagement_type=engagement_type,
    )
    if risk_decision is not None:
        return risk_decision

    ambiguity_decision = identifier_ambiguity_override(
        agent_input,
        business_line=business_line,
        engagement_type=engagement_type,
    )
    if ambiguity_decision is not None:
        return ambiguity_decision

    technical_decision = resolve_technical_route(
        agent_input,
        intent=intent,
        request_flags=request_flags,
        missing_information=missing_information,
        business_line=business_line,
        engagement_type=engagement_type,
        product_names=product_names,
        catalog_numbers=catalog_numbers,
        gray_zone_reasons=gray_zone_reasons,
    )
    if technical_decision is not None:
        return technical_decision

    if gray_zone_reasons:
        return None

    workflow_decision = resolve_workflow_route(
        agent_input,
        intent=intent,
        request_flags=request_flags,
        engagement_type=engagement_type,
        business_line=business_line,
        custom_signals=custom_signals,
        product_names=product_names,
        catalog_numbers=catalog_numbers,
        missing_information=missing_information,
    )
    if workflow_decision is not None:
        return workflow_decision

    commercial_decision = resolve_commercial_route(
        agent_input,
        intent=intent,
        request_flags=request_flags,
        missing_information=missing_information,
        business_line=business_line,
        engagement_type=engagement_type,
        product_names=product_names,
        catalog_numbers=catalog_numbers,
        destination=destination,
        needs_timeline=needs_timeline,
    )
    if commercial_decision is not None:
        return commercial_decision

    operational_decision = resolve_operational_route(
        agent_input,
        intent=intent,
        request_flags=request_flags,
        missing_information=missing_information,
        business_line=business_line,
        engagement_type=engagement_type,
    )
    if operational_decision is not None:
        return operational_decision

    if intent == "partnership_request":
        return finalize_decision(RouteDecision(
            route_name="partnership_review",
            business_line=business_line,
            engagement_type="general_inquiry",
            route_confidence=0.95,
            business_goal="Prepare the partnership inquiry for business review",
            reason="The primary intent is a partnership or business cooperation request.",
            required_capabilities=["business_review"],
            recommended_next_steps=[
                "Summarize the opportunity",
                "Escalate to the business development owner",
            ],
            missing_information_to_request=missing_information,
            should_write_draft=True,
            should_retrieve_knowledge=False,
            should_call_tools=False,
            should_escalate_to_human=True,
        ), agent_input)

    return None


def route_agent_input(runtime_context: RuntimeContext) -> RoutedRuntimeContext:
    agent_input = runtime_context.agent_context.model_dump(mode="json")
    routing_debug = RoutingDebugInfo.model_validate(build_routing_debug_info(agent_input))
    enriched_agent_context = runtime_context.agent_context.model_copy(update={"routing_debug": routing_debug})
    enriched_runtime_context = runtime_context.model_copy(update={"agent_context": enriched_agent_context})
    enriched_input = enriched_agent_context.model_dump(mode="json")

    rule_override = _build_rule_override(enriched_input)
    if rule_override is not None:
        return RoutedRuntimeContext(runtime_context=enriched_runtime_context, route=rule_override)

    routing_chain = _build_routing_chain()
    route = routing_chain.invoke(build_routing_sections(enriched_runtime_context))
    return RoutedRuntimeContext(runtime_context=enriched_runtime_context, route=route)
