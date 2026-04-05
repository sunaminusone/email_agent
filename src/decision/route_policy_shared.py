from __future__ import annotations

from typing import Any

from src.config.routing_config import INTENT_TO_ROUTE
from src.schemas import RouteDecision
from src.schemas.enums import PrimaryIntent, RouteName


INTRO_PATTERNS = [
    "introduce ",
    "tell me about",
    "what is ",
    "who is ",
    "overview of",
    "information about",
]

TECHNICAL_DEEP_DIVE_TERMS = {
    "mechanism", "pathway", "protocol", "troubleshoot", "why", "how", "validation",
    "experiment", "assay", "optimize", "optimization", "workflow", "rationale",
}

CUSTOMER_LOOKUP_TERMS = {
    "customer", "client", "lead", "contact", "phone", "telephone", "mobile",
    "email", "address", "company", "open balance", "balance", "billing address",
    "shipping address", "contact info", "contact information",
}

INVOICE_LOOKUP_TERMS = {
    "invoice", "billing", "bill", "due date", "invoice amount", "invoice status",
    "unpaid", "paid", "payment status", "balance due", "amount due",
}


def safe_intent(agent_input: dict[str, Any]) -> str:
    return agent_input.get("context", {}).get("primary_intent", "unknown")


def safe_risk(agent_input: dict[str, Any]) -> str:
    return agent_input.get("context", {}).get("risk_level", "low")


def safe_missing(agent_input: dict[str, Any]) -> list[str]:
    return agent_input.get("missing_information", [])


def safe_request_flags(agent_input: dict[str, Any]) -> dict[str, Any]:
    return agent_input.get("request_flags", {})


def safe_product_lookup_keys(agent_input: dict[str, Any]) -> dict[str, Any]:
    return agent_input.get("product_lookup_keys", {})


def safe_secondary_intents(agent_input: dict[str, Any]) -> list[str]:
    return agent_input.get("context", {}).get("secondary_intents", [])


def safe_routing_memory(agent_input: dict[str, Any]) -> dict[str, Any]:
    return agent_input.get("routing_memory", {})


def join_values(values: list[str]) -> str:
    cleaned_values = [value for value in values if value]
    return ", ".join(cleaned_values)


def normalize_text(text: str) -> str:
    normalized = text.lower()
    replacements = {
        "car-t": " car_t ",
        "car t": " car_t ",
        "cart ": " car_t ",
        "cart,": " car_t ,",
        "cart.": " car_t .",
        "cart?": " car_t ?",
        "car-nk": " car_nk ",
        "car nk": " car_nk ",
        "mrna-lnp": " mrna_lnp ",
        "mrna lnp": " mrna_lnp ",
        "lnp mrna": " mrna_lnp ",
        "m r n a": " mrna ",
        "l n p": " lnp ",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def combined_text(agent_input: dict[str, Any]) -> str:
    parts = [
        agent_input.get("original_email_text", ""),
        agent_input.get("effective_query", ""),
        agent_input.get("query", ""),
        " ".join(agent_input.get("entities", {}).get("product_names", [])),
        " ".join(agent_input.get("entities", {}).get("targets", [])),
        " ".join(agent_input.get("entities", {}).get("service_names", [])),
        " ".join(agent_input.get("retrieval_hints", {}).get("keywords", [])),
    ]
    return normalize_text(" ".join(part for part in parts if part))


def is_customer_lookup_request(agent_input: dict[str, Any]) -> bool:
    text = combined_text(agent_input)
    company_names = agent_input.get("entities", {}).get("company_names", [])
    request_flags = agent_input.get("request_flags", {})
    if not company_names:
        return False
    if request_flags.get("needs_invoice") or any(term in text for term in INVOICE_LOOKUP_TERMS):
        return False
    return any(term in text for term in CUSTOMER_LOOKUP_TERMS)


def is_invoice_lookup_request(agent_input: dict[str, Any]) -> bool:
    text = combined_text(agent_input)
    order_numbers = agent_input.get("entities", {}).get("order_numbers", [])
    customer_names = agent_input.get("entities", {}).get("company_names", [])
    request_flags = agent_input.get("request_flags", {})

    if not order_numbers and not customer_names and not request_flags.get("needs_invoice"):
        return False
    return request_flags.get("needs_invoice") or any(term in text for term in INVOICE_LOOKUP_TERMS)


def is_intro_style_request(agent_input: dict[str, Any]) -> bool:
    original_query = normalize_text(
        agent_input.get("original_query", "")
        or agent_input.get("effective_query", "")
        or agent_input.get("query", "")
    )
    if not original_query:
        return False
    return any(pattern in original_query for pattern in INTRO_PATTERNS)


def has_catalog_reference(agent_input: dict[str, Any]) -> bool:
    product_lookup_keys = safe_product_lookup_keys(agent_input)
    return any(
        product_lookup_keys.get(key)
        for key in ["product_names", "catalog_numbers", "service_names", "targets"]
    )


def is_deep_technical_request(agent_input: dict[str, Any]) -> bool:
    text = combined_text(agent_input)
    return any(term in text for term in TECHNICAL_DEEP_DIVE_TERMS)


def route_from_intent(intent: str) -> str | None:
    try:
        return INTENT_TO_ROUTE.get(PrimaryIntent(intent))
    except ValueError:
        return None


def route_from_request_flags(request_flags: dict[str, Any]) -> list[str]:
    routes: list[str] = []
    for condition, route_name in [
        (request_flags.get("needs_quote") or request_flags.get("needs_price"), RouteName.PRICING_LOOKUP),
        (request_flags.get("needs_documentation"), RouteName.DOCUMENTATION_LOOKUP),
        (request_flags.get("needs_availability"), RouteName.PRODUCT_LOOKUP),
        (request_flags.get("needs_order_status"), RouteName.ORDER_SUPPORT),
        (request_flags.get("needs_invoice"), RouteName.INVOICE_LOOKUP),
        (request_flags.get("needs_shipping_info"), RouteName.SHIPPING_SUPPORT),
        (request_flags.get("needs_customization"), RouteName.WORKFLOW_AGENT),
    ]:
        if condition and route_name not in routes:
            routes.append(route_name)
    return routes


def route_defaults_for_continuity(route_name: str) -> dict[str, Any]:
    defaults = {
        RouteName.TECHNICAL_RAG: {
            "business_goal": "Resume the technical handling flow with the newly provided context",
            "required_capabilities": ["technical_retrieval", "scientific_reasoning"],
            "should_retrieve_knowledge": True,
            "should_call_tools": False,
        },
        RouteName.COMMERCIAL_AGENT: {
            "business_goal": "Resume the commercial workflow with the newly provided product or documentation details",
            "required_capabilities": ["commercial_tool_selection"],
            "should_retrieve_knowledge": True,
            "should_call_tools": True,
        },
        RouteName.PRICING_LOOKUP: {
            "business_goal": "Resume the pricing workflow with the newly provided commercial details",
            "required_capabilities": ["product_lookup", "quote_support"],
            "should_retrieve_knowledge": False,
            "should_call_tools": True,
        },
        RouteName.PRODUCT_LOOKUP: {
            "business_goal": "Resume the product lookup workflow with the newly provided product details",
            "required_capabilities": ["product_lookup"],
            "should_retrieve_knowledge": False,
            "should_call_tools": True,
        },
        RouteName.DOCUMENTATION_LOOKUP: {
            "business_goal": "Resume the documentation workflow with the newly provided file context",
            "required_capabilities": ["document_lookup"],
            "should_retrieve_knowledge": True,
            "should_call_tools": True,
        },
        RouteName.OPERATIONAL_AGENT: {
            "business_goal": "Resume the operational workflow with the newly provided customer, invoice, order, or shipping details",
            "required_capabilities": ["operational_tool_selection"],
            "should_retrieve_knowledge": False,
            "should_call_tools": True,
        },
        RouteName.WORKFLOW_AGENT: {
            "business_goal": "Resume the structured workflow with the newly provided specification or intake details",
            "required_capabilities": ["workflow_state_management"],
            "should_retrieve_knowledge": False,
            "should_call_tools": True,
        },
        RouteName.ORDER_SUPPORT: {
            "business_goal": "Resume the order-support workflow with the newly provided order details",
            "required_capabilities": ["order_lookup"],
            "should_retrieve_knowledge": False,
            "should_call_tools": True,
        },
        RouteName.SHIPPING_SUPPORT: {
            "business_goal": "Resume the shipping workflow with the newly provided destination or logistics details",
            "required_capabilities": ["shipping_lookup"],
            "should_retrieve_knowledge": False,
            "should_call_tools": True,
        },
        RouteName.COMPLAINT_REVIEW: {
            "business_goal": "Resume the complaint-handling workflow with the newly provided case details",
            "required_capabilities": ["manual_review", "case_summary"],
            "should_retrieve_knowledge": False,
            "should_call_tools": False,
        },
    }
    return defaults.get(
        RouteName(route_name),
        {
            "business_goal": "Resume the active workflow with the newly provided context",
            "required_capabilities": [],
            "should_retrieve_knowledge": False,
            "should_call_tools": False,
        },
    )


def compute_secondary_routes(agent_input: dict[str, Any], primary_route: str) -> list[str]:
    if primary_route in {
        RouteName.COMMERCIAL_AGENT,
        RouteName.OPERATIONAL_AGENT,
        RouteName.WORKFLOW_AGENT,
    }:
        return []

    request_flags = safe_request_flags(agent_input)
    secondary_intents = safe_secondary_intents(agent_input)
    routes: list[str] = []

    for intent in secondary_intents:
        route = route_from_intent(intent)
        if route and route != primary_route and route not in routes:
            routes.append(route)

    for fallback_route in route_from_request_flags(request_flags):
        if fallback_route != primary_route and fallback_route not in routes:
            routes.append(fallback_route)

    return routes


def finalize_decision(decision: RouteDecision, agent_input: dict[str, Any]) -> RouteDecision:
    decision.secondary_routes = compute_secondary_routes(agent_input, decision.route_name)
    return decision
