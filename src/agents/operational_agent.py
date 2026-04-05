from typing import Any, Dict, List

from src.agents.selector import select_operational_tools
from src.agents.utils import make_agent_draft_action, secondary_routes
from src.schemas import ExecutedAction, ExecutionPlan, PlannedAction
from src.schemas.enums import ActionType
from src.tools import (
    execute_customer_lookup,
    execute_invoice_lookup,
    execute_order_lookup,
    execute_shipping_lookup,
)


def _planned(action_id: str, action_type: str, title: str) -> PlannedAction:
    return PlannedAction(action_id=action_id, action_type=action_type, title=title, description=title)


def execute_operational_agent(agent_input: Dict[str, Any], execution_plan: ExecutionPlan) -> List[ExecutedAction]:
    executed_actions: List[ExecutedAction] = []
    selected_tools = select_operational_tools(agent_input, secondary_routes(execution_plan))

    if "customer_lookup" in selected_tools:
        executed_actions.append(
            execute_customer_lookup(_planned("operational-customer", ActionType.LOOKUP_CUSTOMER, "Operational customer lookup"), agent_input)
        )
    if "invoice_lookup" in selected_tools:
        executed_actions.append(
            execute_invoice_lookup(_planned("operational-invoice", ActionType.LOOKUP_INVOICE, "Operational invoice lookup"), agent_input)
        )
    if "order_support" in selected_tools:
        executed_actions.append(
            execute_order_lookup(_planned("operational-order", ActionType.LOOKUP_ORDER, "Operational order lookup"), agent_input)
        )
    if "shipping_support" in selected_tools:
        executed_actions.append(
            execute_shipping_lookup(_planned("operational-shipping", ActionType.LOOKUP_SHIPPING, "Operational shipping lookup"), agent_input)
        )

    facts = {
        "agent": "operational_agent",
        "selected_tools": selected_tools,
        "executed_action_types": [action.action_type for action in executed_actions],
    }
    executed_actions.append(
        make_agent_draft_action("operational-draft", "Operational agent selected and executed the relevant domain tools.", facts)
    )
    return executed_actions
