from __future__ import annotations

from src.tools.models import ToolRequest, ToolResult

from .base import execute_quickbooks_tool
from .request_mapper import build_quickbooks_lookup_params


def execute_order_lookup_tool(request: ToolRequest) -> ToolResult:
    params = build_quickbooks_lookup_params(request)
    order_numbers = params["order_numbers"]
    customer_names = params["customer_names"]
    return execute_quickbooks_tool(
        request=request,
        lookup_mode="quickbooks_order",
        status_key="order_status",
        lookup_label="order",
        request_payload={
            "order_numbers": order_numbers,
            "customer_names": customer_names,
        },
        perform_lookup=lambda client: client.query_transactions(
            order_numbers=order_numbers,
            customer_names=customer_names,
            include_invoices=True,
            include_sales_receipts=True,
        ),
    )
