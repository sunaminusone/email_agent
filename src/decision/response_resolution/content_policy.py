from __future__ import annotations

from .common import INFO_MARKERS, LEAD_TIME_MARKERS, PRODUCT_DETAIL_MARKERS, has_any


def resolve_response_content_plan(agent_input, route, signal_ctx: dict, answer_focus: str) -> dict:
    flags = signal_ctx["flags"]
    query = signal_ctx["query"]
    has_product = signal_ctx["has_product"]
    has_price = signal_ctx["has_price"]
    has_docs = signal_ctx["has_docs"]
    has_technical = signal_ctx["has_technical"]

    if answer_focus == "workflow_status":
        return {
            "content_priority": ["workflow_status", "next_step_guidance"],
            "include_next_step_guidance": False,
            "should_use_summary_responder": False,
            "should_suppress_generic_summary": False,
        }

    if answer_focus == "invoice_status":
        return {
            "content_priority": ["invoice_status", "next_step_guidance"],
            "include_next_step_guidance": True,
            "should_suppress_generic_summary": True,
        }

    if answer_focus == "shipping_status":
        return {
            "content_priority": ["shipping_status", "next_step_guidance"],
            "include_next_step_guidance": True,
            "should_suppress_generic_summary": True,
        }

    if answer_focus == "order_status":
        return {
            "content_priority": ["order_status", "next_step_guidance"],
            "include_next_step_guidance": True,
            "should_suppress_generic_summary": True,
        }

    if answer_focus == "customer_profile":
        return {
            "content_priority": ["customer_profile"],
            "should_suppress_generic_summary": True,
        }

    if answer_focus == "technical_context":
        return {
            "content_priority": ["technical_context", "product_identity", "target_antigen"],
            "include_technical_context": True,
            "include_product_identity": has_product,
            "include_target_antigen": has_product,
            "should_suppress_generic_summary": True,
        }

    if answer_focus == "documentation":
        return {
            "content_priority": ["documents", "product_identity"],
            "include_documents": True,
            "include_product_identity": has_product,
            "include_target_antigen": False,
            "include_application": False,
            "include_species_reactivity": False,
            "should_suppress_generic_summary": True,
        }

    if answer_focus == "lead_time":
        return {
            "content_priority": ["lead_time", "product_identity", "price"],
            "include_product_identity": True,
            "include_price": False,
            "include_lead_time": True,
            "include_target_antigen": False,
            "include_application": False,
            "include_species_reactivity": False,
            "should_suppress_generic_summary": True,
        }

    if answer_focus == "pricing":
        return {
            "content_priority": ["price", "lead_time", "product_identity"],
            "include_product_identity": True,
            "include_price": True,
            "include_lead_time": flags.needs_timeline and has_any(query, LEAD_TIME_MARKERS),
            "include_target_antigen": False,
            "include_application": False,
            "include_species_reactivity": False,
            "should_suppress_generic_summary": True,
        }

    if answer_focus == "product_identity":
        if (
            has_product
            and agent_input.turn_resolution.turn_type in {"follow_up", "clarification_answer"}
            and has_any(query, INFO_MARKERS)
        ):
            return {
                "content_priority": [
                    "product_identity",
                    "target_antigen",
                    "application",
                    "species_reactivity",
                    "technical_context",
                    "price",
                    "lead_time",
                ],
                "include_product_identity": True,
                "include_price": has_price and has_any(query, ["price", "quote", "cost"]),
                "include_lead_time": has_price and has_any(query, LEAD_TIME_MARKERS),
                "include_technical_context": has_technical,
                "include_target_antigen": True,
                "include_application": True,
                "include_species_reactivity": True,
                "should_suppress_generic_summary": True,
            }

        if has_product and has_any(query, PRODUCT_DETAIL_MARKERS):
            return {
                "content_priority": [
                    "product_identity",
                    "target_antigen",
                    "application",
                    "species_reactivity",
                    "technical_context",
                    "documents",
                    "price",
                    "lead_time",
                ],
                "include_product_identity": True,
                "include_target_antigen": True,
                "include_application": True,
                "include_species_reactivity": True,
                "include_price": has_price and has_any(query, ["price", "quote", "cost"]),
                "include_lead_time": has_price and "lead time" in query,
                "include_documents": has_docs and has_any(query, ["brochure", "datasheet", "flyer", "document"]),
                "include_technical_context": has_technical and has_any(query, ["technical", "application", "validation"]),
                "should_suppress_generic_summary": True,
            }

        return {
            "content_priority": ["product_identity", "target_antigen", "price", "lead_time"],
            "include_product_identity": True,
            "include_price": has_price and (flags.needs_price or flags.needs_quote),
            "include_lead_time": has_price and flags.needs_timeline,
            "include_technical_context": has_technical and agent_input.context.primary_intent == "technical_question",
            "include_target_antigen": True,
            "include_application": False,
            "include_species_reactivity": False,
            "should_suppress_generic_summary": route.route_name == "commercial_agent",
        }

    return {
        "content_priority": ["summary"],
        "should_use_summary_responder": True,
    }
