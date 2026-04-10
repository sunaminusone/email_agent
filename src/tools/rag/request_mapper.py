from __future__ import annotations

from typing import Any

from src.tools.models import ToolRequest


def build_rag_lookup_params(request: ToolRequest) -> dict[str, Any]:
    primary_object = request.primary_object
    common_constraints = request.constraints.common
    scope_constraints = request.constraints.scope
    retrieval_constraints = request.constraints.retrieval
    tool_constraints = request.constraints.tool.get("rag", {})
    resolved_constraints = common_constraints.get("resolved_object_constraints", {})

    active_service_name = ""
    active_product_name = ""
    active_target = ""
    product_names: list[str] = []
    service_names: list[str] = []
    targets: list[str] = []

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
        elif primary_object.object_type == "scientific_target":
            active_target = label
            if label:
                targets.append(label)

    product_name = (
        resolved_constraints.get("product_name")
        or ""
    ).strip()
    if product_name:
        product_names.append(product_name)

    service_name = (resolved_constraints.get("service_name") or "").strip()
    if service_name:
        service_names.append(service_name)

    target = (resolved_constraints.get("target") or "").strip()
    if target:
        targets.append(target)

    business_line_hint = (
        (primary_object.business_line if primary_object is not None else "")
        or tool_constraints.get("business_line")
        or retrieval_constraints.get("business_line")
        or resolved_constraints.get("business_line")
        or ""
    )

    return {
        "query": request.query,
        "business_line_hint": business_line_hint,
        "retrieval_hints": tool_constraints.get(
            "retrieval_hints",
            retrieval_constraints.get("hints", {}),
        ),
        "active_service_name": active_service_name or scope_constraints.get("active_service_name", ""),
        "active_product_name": active_product_name or scope_constraints.get("active_product_name", ""),
        "active_target": active_target or scope_constraints.get("active_target", ""),
        "product_names": _dedupe(product_names),
        "service_names": _dedupe(service_names),
        "targets": _dedupe(targets),
        "top_k": 5,
        "scope_context": scope_constraints,
    }


def _dedupe(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered
