from typing import Any, Dict

from src.tools.quickbooks_tool_helper import execute_quickbooks_lookup


def execute_order_lookup(action, agent_input: Dict[str, Any]):
    entities = agent_input.get("entities", {})
    request_flags = agent_input.get("request_flags", {})
    order_numbers = entities.get("order_numbers", [])
    customer_names = entities.get("company_names", [])
    return execute_quickbooks_lookup(
        action=action,
        lookup_mode="quickbooks_order",
        status_key="order_status",
        request_payload={
            "order_numbers": order_numbers,
            "customer_names": customer_names,
        },
        lookup_label="order",
        perform_lookup=lambda client: client.query_transactions(
            order_numbers=order_numbers,
            customer_names=customer_names,
            include_invoices=True,
            include_sales_receipts=not request_flags.get("needs_invoice", False),
        ),
    )
