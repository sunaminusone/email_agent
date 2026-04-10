from __future__ import annotations

from src.tools.models import ToolRequest, ToolResult

from .base import execute_quickbooks_tool
from .request_mapper import build_quickbooks_lookup_params


def execute_customer_lookup_tool(request: ToolRequest) -> ToolResult:
    params = build_quickbooks_lookup_params(request)
    customer_names = params["customer_names"]
    return execute_quickbooks_tool(
        request=request,
        lookup_mode="quickbooks_customer",
        status_key="customer_status",
        lookup_label="customer",
        request_payload={"customer_names": customer_names},
        perform_lookup=lambda client: client.query_customers(customer_names=customer_names),
    )
