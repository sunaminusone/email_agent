from __future__ import annotations

from typing import Any

from src.common.utils import dedupe_strings, first_non_empty
from src.tools.models import ToolRequest


def build_document_lookup_params(request: ToolRequest) -> dict[str, Any]:
    primary_object = request.primary_object
    resolved_constraints = request.constraints.common.get("resolved_object_constraints", {})

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

    catalog_no = first_non_empty(
        resolved_constraints.get("catalog_number"),
        resolved_constraints.get("catalog_no"),
        resolved_constraints.get("identifier"),
    )
    if catalog_no:
        catalog_numbers.append(catalog_no)

    product_name = first_non_empty(
        resolved_constraints.get("product_name"),
        resolved_constraints.get("canonical_value"),
    )
    if product_name:
        product_names.append(product_name)

    document_name = first_non_empty(
        resolved_constraints.get("document_name"),
        resolved_constraints.get("document_title"),
    )
    if document_name:
        document_names.append(document_name)

    business_line_hint = (
        (primary_object.business_line if primary_object is not None else "")
        or resolved_constraints.get("business_line")
        or ""
    )

    return {
        "query": request.query,
        "catalog_numbers": dedupe_strings(catalog_numbers),
        "product_names": dedupe_strings(product_names),
        "document_names": dedupe_strings(document_names),
        "business_line_hint": business_line_hint,
        "top_k": 5,
    }


