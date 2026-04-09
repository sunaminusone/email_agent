from typing import Any, Dict, List

from src.conversation.context_scope import has_current_scope, resolve_effective_scope

from .constants import (
    COMMERCIAL_TOOL_ORDER,
    CUSTOMER_TERMS,
    DOCUMENTATION_TERMS,
    INVOICE_TERMS,
    OPERATIONAL_TOOL_ORDER,
    ORDER_TERMS,
    SHIPPING_TERMS,
    TECHNICAL_TERMS,
)
from .utils import append_unique, has_any, normalized_query


def _should_use_active_service_for_technical_rag(agent_input: Dict[str, Any], query: str) -> bool:
    effective_scope = resolve_effective_scope({**agent_input, "query": query})
    return effective_scope["scope_type"] == "service" and effective_scope["source"] == "active"


def select_commercial_tools(agent_input: Dict[str, Any], hints: List[str] | None = None) -> List[str]:
    query = normalized_query(agent_input)
    context = agent_input.get("context", {})
    entities = agent_input.get("entities", {})
    request_flags = agent_input.get("request_flags", {})
    selected: List[str] = []

    hint_values = hints or []
    for hint in hint_values:
        if hint in COMMERCIAL_TOOL_ORDER:
            append_unique(selected, hint)

    current_scope_present = has_current_scope(agent_input)

    primary_intent = context.get("primary_intent", "")
    secondary_intents = set(context.get("secondary_intents", []))

    if (
        request_flags.get("needs_availability")
        or primary_intent == "product_inquiry"
        or "product_inquiry" in secondary_intents
        or current_scope_present
    ):
        append_unique(selected, "product_lookup")

    if (
        request_flags.get("needs_price")
        or request_flags.get("needs_quote")
        or request_flags.get("needs_timeline")
        or primary_intent == "pricing_question"
        or "pricing_question" in secondary_intents
        or any(term in query for term in ["price", "pricing", "quote", "cost", "lead time"])
    ):
        append_unique(selected, "pricing_lookup")

    if (
        request_flags.get("needs_documentation")
        or request_flags.get("needs_protocol")
        or primary_intent == "documentation_request"
        or "documentation_request" in secondary_intents
        or entities.get("document_names")
        or has_any(query, DOCUMENTATION_TERMS)
    ):
        append_unique(selected, "documentation_lookup")

    if (
        request_flags.get("needs_troubleshooting")
        or request_flags.get("needs_regulatory_info")
        or primary_intent in {"technical_question", "troubleshooting"}
        or bool({"technical_question", "troubleshooting"} & secondary_intents)
        or has_any(query, TECHNICAL_TERMS)
        or _should_use_active_service_for_technical_rag(agent_input, query)
    ):
        append_unique(selected, "technical_rag")

    if not selected:
        append_unique(selected, "product_lookup")

    return [tool for tool in COMMERCIAL_TOOL_ORDER if tool in selected]


def select_operational_tools(agent_input: Dict[str, Any], hints: List[str] | None = None) -> List[str]:
    query = normalized_query(agent_input)
    context = agent_input.get("context", {})
    entities = agent_input.get("entities", {})
    request_flags = agent_input.get("request_flags", {})
    constraints = agent_input.get("constraints", {})
    selected: List[str] = []

    hint_values = hints or []
    for hint in hint_values:
        if hint in OPERATIONAL_TOOL_ORDER:
            append_unique(selected, hint)

    primary_intent = context.get("primary_intent", "")
    secondary_intents = set(context.get("secondary_intents", []))
    company_names = entities.get("company_names", [])
    order_numbers = entities.get("order_numbers", [])
    has_destination = bool(constraints.get("destination"))

    if (
        company_names
        and (
            has_any(query, CUSTOMER_TERMS)
            or primary_intent == "order_support" and "customer" in query
        )
    ):
        append_unique(selected, "customer_lookup")

    if (
        request_flags.get("needs_invoice")
        or primary_intent == "invoice_lookup"
        or "invoice_lookup" in secondary_intents
        or has_any(query, INVOICE_TERMS)
    ) and (order_numbers or company_names or request_flags.get("needs_invoice")):
        append_unique(selected, "invoice_lookup")

    if (
        request_flags.get("needs_order_status")
        or primary_intent == "order_support"
        or "order_support" in secondary_intents
        or has_any(query, ORDER_TERMS)
    ) and (order_numbers or company_names or request_flags.get("needs_order_status")):
        append_unique(selected, "order_support")

    if (
        request_flags.get("needs_shipping_info")
        or primary_intent == "shipping_question"
        or "shipping_question" in secondary_intents
        or has_any(query, SHIPPING_TERMS)
        or has_destination
    ) and (order_numbers or company_names or has_destination or request_flags.get("needs_shipping_info")):
        append_unique(selected, "shipping_support")

    if not selected:
        if company_names:
            append_unique(selected, "customer_lookup")
        elif order_numbers:
            append_unique(selected, "order_support")

    return [tool for tool in OPERATIONAL_TOOL_ORDER if tool in selected]
