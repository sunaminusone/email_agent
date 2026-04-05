from typing import Any, Dict

from src.tools.quickbooks_tool_helper import execute_quickbooks_lookup


def execute_customer_lookup(action, agent_input: Dict[str, Any]):
    entities = agent_input.get("entities", {})
    customer_names = entities.get("company_names", [])
    return execute_quickbooks_lookup(
        action=action,
        lookup_mode="quickbooks_customer",
        status_key="customer_status",
        request_payload={"customer_names": customer_names},
        lookup_label="customer",
        perform_lookup=lambda client: client.query_customers(customer_names=customer_names),
    )
