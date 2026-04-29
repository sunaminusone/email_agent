from __future__ import annotations

from typing import Any

from src.common.utils import dedupe_strings
from src.tools.models import ToolRequest


def build_quickbooks_lookup_params(request: ToolRequest) -> dict[str, Any]:
    primary_object = request.primary_object
    resolved_constraints = request.constraints.common.get("resolved_object_constraints", {})

    customer_names: list[str] = []
    order_numbers: list[str] = []

    if primary_object is not None:
        label = primary_object.canonical_value or primary_object.display_name
        if primary_object.object_type == "customer" and label:
            customer_names.append(label)
        if primary_object.object_type in {"order", "invoice", "shipment"} and primary_object.identifier:
            order_numbers.append(primary_object.identifier)

    customer_name = _first_non_empty(
        resolved_constraints.get("customer_name"),
        resolved_constraints.get("company_name"),
    )
    if customer_name:
        customer_names.append(customer_name)

    order_number = _first_non_empty(
        resolved_constraints.get("order_number"),
        resolved_constraints.get("doc_number"),
        resolved_constraints.get("invoice_number"),
    )
    if order_number:
        order_numbers.append(order_number)

    tool_constraints = request.constraints.tool

    destination = _first_non_empty(
        resolved_constraints.get("destination"),
        resolved_constraints.get("ship_to"),
    )

    # Parser constraints as fallback
    if not destination:
        destination = (tool_constraints.get("destination") or "").strip()
    timeline_requirement = (tool_constraints.get("timeline_requirement") or "").strip()
    quantity = (tool_constraints.get("quantity") or "").strip()

    return {
        "customer_names": dedupe_strings(customer_names),
        "order_numbers": dedupe_strings(order_numbers),
        "destination": destination,
        "timeline_requirement": timeline_requirement,
        "quantity": quantity,
    }


def _first_non_empty(*values: Any) -> str:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""


