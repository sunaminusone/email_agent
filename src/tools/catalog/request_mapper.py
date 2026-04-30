from __future__ import annotations

from typing import Any

from src.common.utils import dedupe_strings
from src.tools.models import ToolRequest


def build_catalog_lookup_params(request: ToolRequest) -> dict[str, Any]:
    primary_object = request.primary_object
    resolved_constraints = request.constraints.common.get("resolved_object_constraints", {})

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

    catalog_no = _first_non_empty(
        resolved_constraints.get("catalog_number"),
        resolved_constraints.get("catalog_no"),
        resolved_constraints.get("identifier"),
    )
    if catalog_no:
        catalog_numbers.append(catalog_no)

    product_name = _first_non_empty(
        resolved_constraints.get("product_name"),
        resolved_constraints.get("canonical_value"),
        resolved_constraints.get("display_name"),
    )
    if product_name:
        product_names.append(product_name)

    service_name = (resolved_constraints.get("service_name") or "").strip()
    if service_name:
        service_names.append(service_name)

    tool_constraints = request.constraints.tool

    target = (resolved_constraints.get("target") or "").strip()
    application = (resolved_constraints.get("application") or "").strip()
    species = (resolved_constraints.get("species") or "").strip()
    format_or_size = (resolved_constraints.get("format_or_size") or "").strip()
    business_line_hint = (
        (primary_object.business_line if primary_object is not None else "")
        or resolved_constraints.get("business_line")
        or ""
    )

    # Parser constraints as fallback when object resolution didn't capture them
    if not format_or_size:
        format_or_size = (tool_constraints.get("format_or_size") or "").strip()

    return {
        "query": request.query,
        "catalog_numbers": dedupe_strings(catalog_numbers),
        "product_names": dedupe_strings(product_names),
        "service_names": dedupe_strings(service_names),
        "targets": dedupe_strings([target] if target else []),
        "applications": dedupe_strings([application] if application else []),
        "species": dedupe_strings([species] if species else []),
        "format_or_size": format_or_size,
        "business_line_hint": business_line_hint,
        "top_k": 10,
    }


def _first_non_empty(*values: Any) -> str:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""


