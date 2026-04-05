from typing import Any, Dict

from src.tools.quickbooks_tool_helper import execute_quickbooks_lookup


def execute_invoice_lookup(action, agent_input: Dict[str, Any]):
    entities = agent_input.get("entities", {})
    order_numbers = entities.get("order_numbers", [])
    customer_names = entities.get("company_names", [])
    return execute_quickbooks_lookup(
        action=action,
        lookup_mode="quickbooks_invoice",
        status_key="invoice_status",
        request_payload={
            "order_numbers": order_numbers,
            "customer_names": customer_names,
        },
        lookup_label="invoice",
        perform_lookup=lambda client: client.query_transactions(
            order_numbers=order_numbers,
            customer_names=customer_names,
            include_invoices=True,
            include_sales_receipts=False,
        ),
    )
