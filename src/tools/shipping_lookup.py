from typing import Any, Dict

from src.tools.quickbooks_tool_helper import execute_quickbooks_lookup
from src.tools.shipping_utils import filter_shipping_matches


def execute_shipping_lookup(action, agent_input: Dict[str, Any]):
    destination = agent_input.get("constraints", {}).get("destination")
    entities = agent_input.get("entities", {})
    order_numbers = entities.get("order_numbers", [])
    customer_names = entities.get("company_names", [])
    return execute_quickbooks_lookup(
        action=action,
        lookup_mode="quickbooks_shipping",
        status_key="shipping_status",
        request_payload={
            "destination": destination,
            "order_numbers": order_numbers,
            "customer_names": customer_names,
        },
        lookup_label="shipping",
        perform_lookup=lambda client: _perform_shipping_lookup(
            client=client,
            destination=destination,
            order_numbers=order_numbers,
            customer_names=customer_names,
        ),
    )


def _perform_shipping_lookup(*, client, destination, order_numbers, customer_names):
    output = client.query_transactions(
        order_numbers=order_numbers,
        customer_names=customer_names,
    )
    output["destination"] = destination
    output["matches"] = filter_shipping_matches(output.get("matches", []), destination)
    return output
