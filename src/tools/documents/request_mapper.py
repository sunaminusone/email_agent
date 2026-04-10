from __future__ import annotations

from typing import Any

from src.tools.models import ToolRequest


def build_document_lookup_params(request: ToolRequest) -> dict[str, Any]:
    primary_object = request.primary_object
    common_constraints = request.constraints.common
    tool_constraints = request.constraints.tool.get("documents", {})
    resolved_constraints = common_constraints.get("resolved_object_constraints", {})

    catalog_numbers: list[str] = []
    product_names: list[str] = []
    document_names: list[str] = []

    if primary_object is not None:
        if primary_object.object_type == "document":
            document_label = primary_object.canonical_value or primary_object.display_name
            if document_label:
                document_names.append(document_label)
        else:
            if primary_object.identifier:
                catalog_numbers.append(primary_object.identifier)
            product_label = primary_object.canonical_value or primary_object.display_name
            if product_label:
                product_names.append(product_label)

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

    document_name = (
        tool_constraints.get("document_name")
        or resolved_constraints.get("document_name")
        or resolved_constraints.get("document_title")
        or ""
    ).strip()
    if document_name:
        document_names.append(document_name)

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
        "document_names": _dedupe(document_names),
        "business_line_hint": business_line_hint,
        "top_k": 5,
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
