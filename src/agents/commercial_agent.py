from typing import Any, Dict, List

from src.agents.selector import select_commercial_tools
from src.agents.utils import make_agent_draft_action, secondary_routes
from src.schemas import ExecutedAction, ExecutionPlan, PlannedAction
from src.schemas.enums import ActionType
from src.tools import (
    execute_documentation_lookup,
    execute_pricing_lookup,
    execute_product_lookup,
    execute_technical_lookup,
)


def _planned(action_id: str, action_type: str, title: str) -> PlannedAction:
    return PlannedAction(action_id=action_id, action_type=action_type, title=title, description=title)


def execute_commercial_agent(agent_input: Dict[str, Any], execution_plan: ExecutionPlan) -> List[ExecutedAction]:
    executed_actions: List[ExecutedAction] = []
    selected_tools = select_commercial_tools(agent_input, secondary_routes(execution_plan))

    if "pricing_lookup" in selected_tools:
        executed_actions.append(
            execute_pricing_lookup(_planned("commercial-price", ActionType.LOOKUP_PRICE, "Commercial price lookup"), agent_input)
        )
    if "product_lookup" in selected_tools:
        executed_actions.append(
            execute_product_lookup(_planned("commercial-product", ActionType.LOOKUP_CATALOG_PRODUCT, "Commercial product lookup"), agent_input)
        )
    if "documentation_lookup" in selected_tools:
        executed_actions.append(
            execute_documentation_lookup(_planned("commercial-docs", ActionType.LOOKUP_DOCUMENT, "Commercial document lookup"), agent_input)
        )
    if "technical_rag" in selected_tools:
        executed_actions.append(
            execute_technical_lookup(_planned("commercial-tech", ActionType.RETRIEVE_TECHNICAL_KNOWLEDGE, "Commercial technical retrieval"), agent_input)
        )

    facts = {
        "agent": "commercial_agent",
        "selected_tools": selected_tools,
        "executed_action_types": [action.action_type for action in executed_actions],
    }
    executed_actions.append(
        make_agent_draft_action("commercial-draft", "Commercial agent selected and executed the relevant domain tools.", facts)
    )
    return executed_actions
