from __future__ import annotations

from .common import (
    INFO_MARKERS,
    LEAD_TIME_MARKERS,
    PRODUCT_DETAIL_MARKERS,
    has_any,
)


def resolve_response_focus(agent_input, route, signal_ctx: dict) -> dict:
    flags = signal_ctx["flags"]
    query = signal_ctx["query"]
    grounded_actions = signal_ctx["grounded_actions"]

    has_product = signal_ctx["has_product"]
    has_price = signal_ctx["has_price"]
    has_docs = signal_ctx["has_docs"]
    has_technical = signal_ctx["has_technical"]
    has_customer = signal_ctx["has_customer"]
    has_invoice = signal_ctx["has_invoice"]
    has_order = signal_ctx["has_order"]
    has_shipping = signal_ctx["has_shipping"]

    if route.route_name == "workflow_agent":
        return {
            "answer_focus": "workflow_status",
            "primary_action_type": "prepare_customization_intake",
            "supporting_action_types": [],
            "preferred_route_name": "workflow_agent",
            "reason": "Workflow requests should respond through the workflow responder.",
            "confidence": 0.98,
        }

    if route.route_name == "operational_agent":
        if has_invoice and (flags.needs_invoice or has_any(query, ["invoice", "billing", "bill"])):
            return {
                "answer_focus": "invoice_status",
                "primary_action_type": "lookup_invoice",
                "supporting_action_types": [action for action in grounded_actions if action != "lookup_invoice"],
                "preferred_route_name": "invoice_lookup",
                "reason": "The current turn is asking for invoice information.",
                "confidence": 0.95,
            }
        if has_shipping and (flags.needs_shipping_info or has_any(query, ["shipping", "delivery", "tracking", "destination"])):
            return {
                "answer_focus": "shipping_status",
                "primary_action_type": "lookup_shipping",
                "supporting_action_types": [action for action in grounded_actions if action != "lookup_shipping"],
                "preferred_route_name": "shipping_support",
                "reason": "The current turn is asking for shipping information.",
                "confidence": 0.95,
            }
        if has_order and (flags.needs_order_status or has_any(query, ["order", "purchase", "order status"])):
            return {
                "answer_focus": "order_status",
                "primary_action_type": "lookup_order",
                "supporting_action_types": [action for action in grounded_actions if action != "lookup_order"],
                "preferred_route_name": "order_support",
                "reason": "The current turn is asking for order status information.",
                "confidence": 0.95,
            }
        if has_customer:
            return {
                "answer_focus": "customer_profile",
                "primary_action_type": "lookup_customer",
                "supporting_action_types": [action for action in grounded_actions if action != "lookup_customer"],
                "preferred_route_name": "customer_lookup",
                "reason": "Customer details are the strongest grounded result for this turn.",
                "confidence": 0.9,
            }

    if has_technical and (
        flags.needs_troubleshooting
        or flags.needs_regulatory_info
        or agent_input.context.primary_intent in {"technical_question", "troubleshooting"}
    ):
        return {
            "answer_focus": "technical_context",
            "primary_action_type": "retrieve_technical_knowledge",
            "supporting_action_types": [action for action in grounded_actions if action != "retrieve_technical_knowledge"],
            "preferred_route_name": "technical_rag",
            "reason": "The current turn is primarily technical.",
            "confidence": 0.95,
        }

    if has_product and (
        agent_input.turn_resolution.turn_type in {"follow_up", "clarification_answer"}
        and has_any(query, INFO_MARKERS)
    ):
        return {
            "answer_focus": "product_identity",
            "primary_action_type": "lookup_catalog_product",
            "supporting_action_types": [action for action in grounded_actions if action != "lookup_catalog_product"],
            "preferred_route_name": "product_lookup",
            "reason": "The current turn is a follow-up asking for more product information.",
            "confidence": 0.9,
        }

    if flags.needs_documentation and has_docs:
        return {
            "answer_focus": "documentation",
            "primary_action_type": "lookup_document",
            "supporting_action_types": [action for action in grounded_actions if action != "lookup_document"],
            "preferred_route_name": "documentation_lookup",
            "reason": "The current turn is asking for documentation.",
            "confidence": 0.98,
        }

    if has_price and has_any(query, LEAD_TIME_MARKERS):
        return {
            "answer_focus": "lead_time",
            "primary_action_type": "lookup_price",
            "supporting_action_types": [action for action in grounded_actions if action != "lookup_price"],
            "preferred_route_name": "pricing_lookup",
            "reason": "The current turn is specifically asking about lead time.",
            "confidence": 0.98,
        }

    if (flags.needs_price or flags.needs_quote) and has_price:
        return {
            "answer_focus": "pricing",
            "primary_action_type": "lookup_price",
            "supporting_action_types": [action for action in grounded_actions if action != "lookup_price"],
            "preferred_route_name": "pricing_lookup",
            "reason": "The current turn is asking for price or quote information.",
            "confidence": 0.97,
        }

    if has_product and has_any(query, PRODUCT_DETAIL_MARKERS):
        return {
            "answer_focus": "product_identity",
            "primary_action_type": "lookup_catalog_product",
            "supporting_action_types": [action for action in grounded_actions if action != "lookup_catalog_product"],
            "preferred_route_name": "product_lookup",
            "reason": "The current turn asks for general product details.",
            "confidence": 0.88,
        }

    if has_product:
        return {
            "answer_focus": "product_identity",
            "primary_action_type": "lookup_catalog_product",
            "supporting_action_types": [action for action in grounded_actions if action != "lookup_catalog_product"],
            "preferred_route_name": "product_lookup",
            "reason": "Product lookup is the strongest grounded basis for this reply.",
            "confidence": 0.88,
        }

    return {
        "answer_focus": "summary",
        "primary_action_type": grounded_actions[0] if grounded_actions else "",
        "supporting_action_types": grounded_actions[1:] if len(grounded_actions) > 1 else [],
        "preferred_route_name": route.route_name,
        "reason": "No narrower answer focus was identified, so a summary response is appropriate.",
        "confidence": 0.6 if grounded_actions else 0.0,
    }
