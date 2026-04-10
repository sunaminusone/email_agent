from __future__ import annotations

from src.tools.models import ToolRequest, ToolResult

from .base import execute_quickbooks_tool
from .filters import filter_shipping_matches
from .request_mapper import build_quickbooks_lookup_params


def execute_shipping_lookup_tool(request: ToolRequest) -> ToolResult:
    params = build_quickbooks_lookup_params(request)
    order_numbers = params["order_numbers"]
    customer_names = params["customer_names"]
    destination = params["destination"]
    return execute_quickbooks_tool(
        request=request,
        lookup_mode="quickbooks_shipping",
        status_key="shipping_status",
        lookup_label="shipping",
        request_payload={
            "destination": destination,
            "order_numbers": order_numbers,
            "customer_names": customer_names,
        },
        perform_lookup=lambda client: _perform_shipping_lookup(
            client=client,
            destination=destination,
            order_numbers=order_numbers,
            customer_names=customer_names,
        ),
    )


def _perform_shipping_lookup(
    *,
    client,
    destination: str,
    order_numbers: list[str],
    customer_names: list[str],
) -> dict[str, object]:
    output = client.query_transactions(
        order_numbers=order_numbers,
        customer_names=customer_names,
    )
    output["destination"] = destination
    output["matches"] = filter_shipping_matches(output.get("matches", []), destination)
    return output
