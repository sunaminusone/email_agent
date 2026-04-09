from __future__ import annotations

import re
from typing import Any

from src.catalog.product_registry import lookup_products_by_alias
from src.conversation.context_scope import has_current_scope, query_has_service_scope_marker, resolve_effective_scope
from src.rag.service_page_ingestion import load_service_page_documents
from src.schemas import RouteDecision
from src.strategies import detect_business_line, detect_engagement_type

from .route_policy_shared import (
    finalize_decision,
    route_defaults_for_continuity,
)


_REFERENTIAL_SCOPE_PATTERNS = (
    re.compile(r"\bthis antibody\b", re.I),
    re.compile(r"\bthat antibody\b", re.I),
    re.compile(r"\bthis service\b", re.I),
    re.compile(r"\bthat service\b", re.I),
    re.compile(r"\bthis product\b", re.I),
    re.compile(r"\bthat product\b", re.I),
    re.compile(r"\bthat one\b", re.I),
    re.compile(r"\bthe product\b", re.I),
    re.compile(r"\bthe service\b", re.I),
    re.compile(r"\bit\b", re.I),
    re.compile(r"\bits\b", re.I),
)


def _first_non_empty(values: list[str]) -> str:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""


def _format_ambiguous_product_candidates(alias: str, matches: list[dict[str, Any]]) -> str:
    lines = [f'I found multiple products matching "{alias}". Please choose one:']
    for match in matches:
        catalog_no = str(match.get("catalog_no") or "").strip()
        name = str(match.get("canonical_name") or match.get("name") or "").strip()
        if catalog_no and name:
            lines.append(f"- {catalog_no} | {name}")
        elif catalog_no:
            lines.append(f"- {catalog_no}")
        elif name:
            lines.append(f"- {name}")
    lines.append("You can reply with the catalog number only.")
    return "\n".join(lines)


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


def ambiguous_product_alias_override(
    agent_input: dict[str, Any],
    *,
    business_line: str,
    engagement_type: str,
) -> RouteDecision | None:
    product_lookup_keys = agent_input.get("product_lookup_keys", {})
    catalog_numbers = list(product_lookup_keys.get("catalog_numbers", []) or [])
    if catalog_numbers:
        return None

    product_names = list(product_lookup_keys.get("product_names", []) or [])
    alias = _first_non_empty(product_names)
    if not alias:
        return None

    matches = lookup_products_by_alias(alias)
    if len(matches) <= 1:
        return None

    question = _format_ambiguous_product_candidates(alias, matches)
    return finalize_decision(RouteDecision(
        route_name="clarification_request",
        business_line=business_line,
        engagement_type=engagement_type,
        route_confidence=0.97,
        business_goal="Clarify which product the user means when a product alias maps to multiple catalog items",
        reason="The product alias matches multiple catalog products, so the system should ask the user to choose a specific product instead of guessing.",
        required_capabilities=["clarification_generation"],
        recommended_next_steps=[
            "Show all matched product candidates to the user",
            "Ask the user to reply with the desired catalog number or exact product name",
        ],
        missing_information_to_request=[question],
        should_write_draft=True,
        should_retrieve_knowledge=False,
        should_call_tools=False,
        should_escalate_to_human=False,
    ), agent_input)

def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").replace("-", " ").split())


def _detect_referential_phrase(agent_input: dict[str, Any]) -> str:
    referenced = str(
        ((agent_input.get("open_slots") or {}).get("referenced_prior_context") or "")
    ).strip()
    if referenced:
        return referenced

    query = str(
        agent_input.get("original_query", "")
        or agent_input.get("effective_query", "")
        or agent_input.get("query", "")
    )
    for pattern in _REFERENTIAL_SCOPE_PATTERNS:
        match = pattern.search(query)
        if match:
            return match.group(0)
    return ""


def missing_referential_scope_override(
    agent_input: dict[str, Any],
    *,
    intent: str,
    business_line: str,
    engagement_type: str,
) -> RouteDecision | None:
    if has_current_scope(agent_input):
        return None

    effective_scope = resolve_effective_scope(agent_input)
    if effective_scope["scope_type"]:
        return None

    if intent not in {
        "technical_question",
        "documentation_request",
        "follow_up",
        "general_info",
        "timeline_question",
        "unknown",
    }:
        return None

    referential_phrase = _detect_referential_phrase(agent_input)
    if not referential_phrase:
        return None

    normalized_phrase = _normalize_text(referential_phrase)
    if "antibody" in normalized_phrase or "product" in normalized_phrase:
        question = (
            "Could you clarify which antibody or product you mean? "
            "A product name or catalog number works best."
        )
    elif "service" in normalized_phrase:
        question = "Could you clarify which service you mean?"
    else:
        question = "Could you clarify which product or service you mean?"

    return finalize_decision(RouteDecision(
        route_name="clarification_request",
        business_line=business_line,
        engagement_type=engagement_type,
        route_confidence=0.95,
        business_goal="Clarify the missing referenced object before continuing the follow-up request",
        reason="The query depends on prior context, but no active or current scope is available to resolve the referenced product or service safely.",
        required_capabilities=["clarification_generation"],
        recommended_next_steps=[
            "Ask which product or service the user is referring to",
            "Resume the technical, commercial, or documentation flow once the object is confirmed",
        ],
        missing_information_to_request=[question],
        should_write_draft=True,
        should_retrieve_knowledge=False,
        should_call_tools=False,
        should_escalate_to_human=False,
    ), agent_input)


def _service_names_for_business_line(business_line: str) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    normalized_line = str(business_line or "").strip()
    for document in load_service_page_documents():
        metadata = dict(document.metadata)
        if metadata.get("entity_type") not in {"service", "service_plan", "service_phase", "service_plan_summary", "workflow_step"}:
            continue
        if normalized_line and normalized_line not in {"unknown", "cross_line"}:
            if metadata.get("business_line") != normalized_line:
                continue
        service_name = str(metadata.get("service_name") or metadata.get("parent_service") or "").strip()
        if not service_name:
            continue
        lowered = service_name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        labels.append(service_name)
    return labels


def service_scope_ambiguity_override(
    agent_input: dict[str, Any],
    *,
    intent: str,
    business_line: str,
    engagement_type: str,
) -> RouteDecision | None:
    if has_current_scope(agent_input):
        return None

    effective_scope = resolve_effective_scope(agent_input)
    if effective_scope["scope_type"]:
        return None

    normalized_query = _normalize_text(
        agent_input.get("original_query", "")
        or agent_input.get("effective_query", "")
        or agent_input.get("query", "")
    )
    if not normalized_query:
        return None

    if intent not in {"technical_question", "general_info", "follow_up", "documentation_request", "unknown"}:
        return None

    if not query_has_service_scope_marker(normalized_query):
        return None

    service_options = _service_names_for_business_line(business_line)
    if business_line and business_line not in {"unknown", "cross_line"} and len(service_options) == 1:
        return None

    if service_options:
        options_text = ", ".join(service_options[:4])
        question = f"Please confirm which service you mean: {options_text}."
    else:
        question = (
            "Please confirm which service you mean before I answer. "
            "If helpful, you can name the service or business line."
        )

    return finalize_decision(RouteDecision(
        route_name="clarification_request",
        business_line=business_line,
        engagement_type=engagement_type,
        route_confidence=0.93,
        business_goal="Clarify the target service before answering a service-specific follow-up question",
        reason="The query asks about service-specific capabilities, but no explicit or active service is available to scope the answer reliably.",
        required_capabilities=["clarification_generation"],
        recommended_next_steps=[
            "Ask which service the user is referring to",
            "Resume the technical or commercial answer once the target service is confirmed",
        ],
        missing_information_to_request=[question],
        should_write_draft=True,
        should_retrieve_knowledge=False,
        should_call_tools=False,
        should_escalate_to_human=False,
    ), agent_input)
