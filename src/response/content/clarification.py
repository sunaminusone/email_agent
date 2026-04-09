from __future__ import annotations

from typing import Any

from src.schemas import FinalResponse, ResponseTopic, RouteDecision


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _requested_customer_fields(query: str) -> set[str]:
    normalized = _normalize_text(query)
    fields = set()

    if any(term in normalized for term in ["email", "e-mail", "mail"]):
        fields.add("email")
    if any(term in normalized for term in ["phone", "telephone", "mobile", "contact number"]):
        fields.add("phone")
    if any(term in normalized for term in ["address", "billing address", "shipping address", "location"]):
        fields.add("address")
    if any(term in normalized for term in ["open balance", "balance", "owed", "owes", "欠款", "余额"]):
        fields.add("open_balance")
    if any(term in normalized for term in ["profile", "details", "info", "information", "资料", "详情", "客户信息"]):
        fields.add("full_profile")

    return fields


def clean_missing_information(
    route: RouteDecision,
    query: str,
    agent_input: dict,
    missing_information: list[str],
) -> list[str]:
    if not missing_information:
        return []

    normalized_query = _normalize_text(query)
    normalized_route_business_line = _normalize_text(route.business_line)
    company_names = agent_input.get("entities", {}).get("company_names", [])
    normalized_companies = {_normalize_text(name) for name in company_names if name}
    requested_customer_fields = _requested_customer_fields(query)
    product_lookup_keys = agent_input.get("product_lookup_keys", {})
    has_product_identifier = bool(
        product_lookup_keys.get("catalog_numbers")
        or product_lookup_keys.get("product_names")
        or product_lookup_keys.get("service_names")
        or product_lookup_keys.get("targets")
    )
    cleaned: list[str] = []

    for item in missing_information:
        normalized_item = _normalize_text(item)
        if not normalized_item:
            continue

        if normalized_item == normalized_query or normalized_item in normalized_query:
            continue

        if normalized_item.startswith("user did not specify"):
            continue

        if normalized_item.startswith("please confirm whether you need the brochure for"):
            query_mentions_business_line = any(
                token in normalized_query
                for token in ["antibody", "car-t", "car_t", "car t", "car-nk", "car_nk", "mrna_lnp", "mrna-lnp", "other service"]
            )
            route_already_has_business_line = normalized_route_business_line not in {"", "unknown"}
            if query_mentions_business_line or route_already_has_business_line:
                continue

        if "business line" in normalized_item:
            query_mentions_business_line = any(
                token in normalized_query
                for token in ["antibody", "car-t", "car_t", "car t", "car-nk", "car_nk", "mrna_lnp", "mrna-lnp", "other service"]
            )
            route_already_has_business_line = normalized_route_business_line not in {"", "unknown"}
            if query_mentions_business_line or route_already_has_business_line:
                continue

        if has_product_identifier and any(
            hint in normalized_item
            for hint in ["product name", "catalog number", "catalog no", "identifier", "alias", "target"]
        ):
            continue

        if route.route_name == "customer_lookup":
            if normalized_companies and any(company in normalized_item for company in normalized_companies):
                continue
            if requested_customer_fields and any(field.replace("_", " ") in normalized_item for field in requested_customer_fields):
                continue

        cleaned.append(item)

    return cleaned


def _direct_clarification_question(missing_information: list[str]) -> str:
    if len(missing_information) != 1:
        return ""
    candidate = (missing_information[0] or "").strip()
    if candidate.startswith("Please confirm whether ") and candidate.endswith("."):
        return candidate
    if candidate.startswith("I found multiple products matching "):
        return candidate
    return ""


def build_deterministic_response(
    *,
    route: RouteDecision,
    effective_route_name: str,
    missing_information: list[str],
    action_types: list[str],
    language: str,
    response_topic,
) -> dict:
    effective_topic = response_topic
    deterministic_response = None

    if route.should_escalate_to_human:
        effective_topic = ResponseTopic.HANDOFF
        if language == "zh":
            deterministic_response = FinalResponse(
                message="这个问题需要人工进一步处理。我已经整理了当前上下文，建议转给对应同事继续跟进。",
                response_type="handoff",
                needs_human_handoff=True,
                grounded_action_types=action_types,
            )
        else:
            deterministic_response = FinalResponse(
                message="This case needs human review. I have enough context to hand it off for manual follow-up.",
                response_type="handoff",
                needs_human_handoff=True,
                grounded_action_types=action_types,
            )
    elif missing_information and effective_route_name not in {"customer_lookup", "order_support", "shipping_support", "workflow_agent"}:
        effective_topic = ResponseTopic.CLARIFICATION
        direct_question = _direct_clarification_question(missing_information)
        if direct_question:
            deterministic_response = FinalResponse(
                message=direct_question,
                response_type="clarification",
                missing_information_requested=missing_information[:1],
                grounded_action_types=action_types,
            )
        elif language == "zh":
            details = "；".join(missing_information[:3])
            deterministic_response = FinalResponse(
                message=f"要继续处理这个问题，我还需要这些信息：{details}。",
                response_type="clarification",
                missing_information_requested=missing_information[:3],
                grounded_action_types=action_types,
            )
        else:
            details = "; ".join(missing_information[:3])
            deterministic_response = FinalResponse(
                message=f"To continue, I still need these details: {details}.",
                response_type="clarification",
                missing_information_requested=missing_information[:3],
                grounded_action_types=action_types,
            )

    return {
        "effective_topic": effective_topic,
        "deterministic_response": deterministic_response,
    }
