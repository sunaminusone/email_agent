from __future__ import annotations

from typing import Any

from src.tools.models import ToolRequest


def build_catalog_lookup_params(request: ToolRequest) -> dict[str, Any]:
    primary_object = request.primary_object
    common_constraints = request.constraints.common
    tool_constraints = request.constraints.tool.get("catalog", {})
    resolved_constraints = common_constraints.get("resolved_object_constraints", {})

    catalog_numbers: list[str] = []
    product_names: list[str] = []
    service_names: list[str] = []

    if primary_object is not None:
        if primary_object.identifier:
            catalog_numbers.append(primary_object.identifier)
        canonical_value = primary_object.canonical_value or primary_object.display_name
        if primary_object.object_type == "service":
            if canonical_value:
                service_names.append(canonical_value)
        elif canonical_value:
            product_names.append(canonical_value)

    catalog_no = (
        tool_constraints.get("catalog_number")
        or resolved_constraints.get("catalog_number")
        or ""
    ).strip()
    if catalog_no:
        catalog_numbers.append(catalog_no)

    product_name = (
        tool_constraints.get("product_name")
        or resolved_constraints.get("product_name")
        or ""
    ).strip()
    if product_name:
        product_names.append(product_name)

    service_name = (tool_constraints.get("service_name") or resolved_constraints.get("service_name") or "").strip()
    if service_name:
        service_names.append(service_name)

    target = (tool_constraints.get("target") or resolved_constraints.get("target") or "").strip()
    application = (tool_constraints.get("application") or resolved_constraints.get("application") or "").strip()
    species = (tool_constraints.get("species") or resolved_constraints.get("species") or "").strip()
    format_or_size = (tool_constraints.get("format_or_size") or resolved_constraints.get("format_or_size") or "").strip()
    business_line_hint = (
        (primary_object.business_line if primary_object is not None else "")
        or tool_constraints.get("business_line")
        or resolved_constraints.get("business_line")
        or ""
    )

    return {
        "query": request.query,
        "catalog_numbers": _dedupe(catalog_numbers),
        "product_names": _dedupe(product_names),
        "service_names": _dedupe(service_names),
        "targets": _dedupe([target] if target else []),
        "applications": _dedupe([application] if application else []),
        "species": _dedupe([species] if species else []),
        "format_or_size": format_or_size,
        "business_line_hint": business_line_hint,
        "top_k": 10,
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
