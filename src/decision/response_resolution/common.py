from __future__ import annotations

from typing import Iterable

from src.schemas import AgentContext, ExecutionRun


def has_action(execution_run: ExecutionRun, action_type: str) -> bool:
    return any(
        action.action_type == action_type and action.status in {"completed", "not_found", "blocked"}
        for action in execution_run.executed_actions
    )


def grounded_action_types(execution_run: ExecutionRun) -> list[str]:
    return [action.action_type for action in execution_run.executed_actions if action.status != "pending"]


def normalized_query(agent_input: AgentContext) -> str:
    return " ".join(
        part.strip().lower()
        for part in [
            agent_input.query or "",
            agent_input.effective_query or "",
            agent_input.retrieval_query or "",
        ]
        if part and part.strip()
    )


def has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


INFO_MARKERS = {
    "other information",
    "more information",
    "more info",
    "additional information",
    "additional info",
    "more details",
    "tell me more",
    "anything else",
    "other details",
}

PRODUCT_DETAIL_MARKERS = {
    "information",
    "info",
    "details",
    "detail",
    "tell me more",
    "more about",
    "background",
}

LEAD_TIME_MARKERS = {
    "lead time",
    "timeline",
    "turnaround time",
    "turnaround",
    "delivery time",
    "ship time",
}

CONCISE_STYLE_MARKERS = {
    "concise",
    "brief",
    "short",
    "quick",
    "quickly",
}

CUSTOMER_FRIENDLY_MARKERS = {
    "customer-friendly",
    "customer friendly",
    "client-friendly",
    "client friendly",
    "for a customer",
    "for the customer",
    "customer-facing",
    "client-facing",
}

TECHNICAL_STYLE_MARKERS = {
    "technical",
    "scientific",
    "mechanism",
    "validation",
    "protocol",
    "technical note",
}


def build_response_signal_context(agent_input: AgentContext, execution_run: ExecutionRun) -> dict:
    return {
        "flags": agent_input.request_flags,
        "query": normalized_query(agent_input),
        "grounded_actions": grounded_action_types(execution_run),
        "has_product": has_action(execution_run, "lookup_catalog_product"),
        "has_price": has_action(execution_run, "lookup_price"),
        "has_docs": has_action(execution_run, "lookup_document"),
        "has_technical": has_action(execution_run, "retrieve_technical_knowledge"),
        "has_customer": has_action(execution_run, "lookup_customer"),
        "has_invoice": has_action(execution_run, "lookup_invoice"),
        "has_order": has_action(execution_run, "lookup_order"),
        "has_shipping": has_action(execution_run, "lookup_shipping"),
    }
