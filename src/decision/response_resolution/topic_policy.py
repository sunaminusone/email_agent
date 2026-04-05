from __future__ import annotations

from src.schemas import ResponseTopic


def _topic_for_focus(answer_focus: str, route_name: str) -> ResponseTopic:
    if answer_focus == "workflow_status" or route_name == "workflow_agent":
        return ResponseTopic.WORKFLOW_STATUS
    if answer_focus in {"invoice_status", "shipping_status", "order_status", "customer_profile"} or route_name == "operational_agent":
        return ResponseTopic.OPERATIONAL_STATUS
    if answer_focus == "technical_context" or route_name == "technical_rag":
        return ResponseTopic.TECHNICAL_DOC
    if answer_focus == "documentation":
        return ResponseTopic.DOCUMENT_DELIVERY
    if answer_focus in {"pricing", "lead_time"}:
        return ResponseTopic.COMMERCIAL_QUOTE
    if answer_focus == "product_identity":
        return ResponseTopic.PRODUCT_INFO
    return ResponseTopic.GENERAL_CHAT


def resolve_response_topic(*, answer_focus: str, route_name: str) -> ResponseTopic:
    return _topic_for_focus(answer_focus, route_name)
