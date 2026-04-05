from __future__ import annotations

from src.responders import render_structured_response
from src.schemas import ResponseTopic, RouteDecision


LEGACY_FALLBACK_ALLOWED_TOPICS = {
    ResponseTopic.GENERAL_CHAT.value,
}


def effective_route_name(route: RouteDecision, execution_run) -> str:
    if route.route_name not in {"commercial_agent", "operational_agent"}:
        return route.route_name

    action_types = [action.action_type for action in execution_run.executed_actions]
    if route.route_name == "commercial_agent":
        if "lookup_price" in action_types:
            return "pricing_lookup"
        if "lookup_document" in action_types:
            return "documentation_lookup"
        if "lookup_catalog_product" in action_types:
            return "product_lookup"
        if "retrieve_technical_knowledge" in action_types:
            return "technical_rag"
    if route.route_name == "operational_agent":
        if "lookup_customer" in action_types:
            return "customer_lookup"
        if "lookup_invoice" in action_types:
            return "invoice_lookup"
        if "lookup_order" in action_types:
            return "order_support"
        if "lookup_shipping" in action_types:
            return "shipping_support"
    return route.route_name


def route_for_response(route: RouteDecision, route_name: str) -> RouteDecision:
    if not route_name or route_name == route.route_name:
        return route
    return route.model_copy(update={"route_name": route_name})


def resolve_legacy_fallback(
    *,
    agent_input,
    route: RouteDecision,
    focused_route: RouteDecision,
    execution_run,
    response_resolution,
    action_types: list[str],
):
    topic_type = response_resolution.topic_type.value if hasattr(response_resolution.topic_type, "value") else str(response_resolution.topic_type)
    if topic_type not in LEGACY_FALLBACK_ALLOWED_TOPICS:
        return {
            "response": None,
            "route_name": "",
            "responder_name": "",
            "reason": f"disabled_for_topic:{topic_type}",
        }

    legacy_fallback_result = render_structured_response(
        agent_input,
        focused_route,
        execution_run,
        response_resolution,
        action_types,
    )
    if legacy_fallback_result is not None:
        return {
            **legacy_fallback_result,
            "reason": "allowed_general_chat_summary",
        }

    if focused_route.route_name != route.route_name:
        legacy_fallback_result = render_structured_response(
            agent_input,
            route,
            execution_run,
            response_resolution,
            action_types,
        )
        if legacy_fallback_result is not None:
            return {
                **legacy_fallback_result,
                "reason": "allowed_general_chat_summary_original_route",
            }

    return {
        "response": None,
        "route_name": "",
        "responder_name": "",
        "reason": "no_legacy_summary_available",
    }
