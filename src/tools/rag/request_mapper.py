from __future__ import annotations

from typing import Any

from src.common.utils import dedupe_strings
from src.tools.models import ToolRequest


def _build_retrieval_context(request: ToolRequest) -> dict[str, Any]:
    tool_constraints = request.constraints.tool
    retrieval_hints = request.constraints.retrieval.get("hints", {})

    context: dict[str, Any] = {}

    scalar_fields = (
        "usage_context",
        "experiment_type",
        "customer_goal",
        "pain_point",
        "requested_action",
        "regulatory_or_compliance_note",
    )
    for field_name in scalar_fields:
        value = str(tool_constraints.get(field_name) or "").strip()
        if value:
            context[field_name] = value

    keywords = [
        str(keyword).strip()
        for keyword in (retrieval_hints.get("keywords") or [])
        if str(keyword).strip()
    ]
    if keywords:
        context["keywords"] = dedupe_strings(keywords)

    return context


def build_rag_lookup_params(request: ToolRequest) -> dict[str, Any]:
    primary_object = request.primary_object
    scope_constraints = request.constraints.scope
    retrieval_constraints = request.constraints.retrieval
    resolved_constraints = request.constraints.common.get("resolved_object_constraints", {})

    active_service_name = ""
    active_product_name = ""
    product_names: list[str] = []
    service_names: list[str] = []

    if primary_object is not None:
        label = primary_object.canonical_value or primary_object.display_name
        if primary_object.object_type == "service":
            active_service_name = label
            if label:
                service_names.append(label)
        elif primary_object.object_type == "product":
            active_product_name = label
            if label:
                product_names.append(label)

    product_name = (resolved_constraints.get("product_name") or "").strip()
    if product_name:
        product_names.append(product_name)

    service_name = (resolved_constraints.get("service_name") or "").strip()
    if service_name:
        service_names.append(service_name)

    business_line_hint = (
        (primary_object.business_line if primary_object is not None else "")
        or retrieval_constraints.get("business_line")
        or resolved_constraints.get("business_line")
        or ""
    )

    return {
        "query": request.query,
        "business_line_hint": business_line_hint,
        "retrieval_hints": retrieval_constraints.get("hints", {}),
        "retrieval_context": _build_retrieval_context(request),
        "active_service_name": active_service_name or scope_constraints.get("active_service_name", ""),
        "active_product_name": active_product_name or scope_constraints.get("active_product_name", ""),
        "product_names": dedupe_strings(product_names),
        "service_names": dedupe_strings(service_names),
        "top_k": 5,
        "scope_context": scope_constraints,
    }

