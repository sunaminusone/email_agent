from __future__ import annotations

from typing import Any

from src.tools.models import ToolRequest


def build_quickbooks_lookup_params(request: ToolRequest) -> dict[str, Any]:
    primary_object = request.primary_object
    common_constraints = request.constraints.common
    tool_constraints = request.constraints.tool.get("quickbooks", {})
    resolved_constraints = common_constraints.get("resolved_object_constraints", {})

    customer_names: list[str] = []
    order_numbers: list[str] = []

    if primary_object is not None:
        label = primary_object.canonical_value or primary_object.display_name
        if primary_object.object_type == "customer" and label:
            customer_names.append(label)
        if primary_object.object_type in {"order", "invoice", "shipment"} and primary_object.identifier:
            order_numbers.append(primary_object.identifier)

    customer_name = (
        tool_constraints.get("customer_name")
        or resolved_constraints.get("customer_name")
        or ""
    ).strip()
    if customer_name:
        customer_names.append(customer_name)

    order_number = (
        tool_constraints.get("order_number")
        or resolved_constraints.get("order_number")
        or ""
    ).strip()
    if order_number:
        order_numbers.append(order_number)

    invoice_number = ""
    if invoice_number:
        order_numbers.append(invoice_number)

    destination = (
        tool_constraints.get("destination")
        or resolved_constraints.get("destination")
        or ""
    ).strip()

    return {
        "customer_names": _dedupe(customer_names),
        "order_numbers": _dedupe(order_numbers),
        "destination": destination,
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
