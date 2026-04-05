from typing import Any, Dict

from src.agents import (
    execute_commercial_agent,
    execute_operational_agent,
    execute_workflow_agent,
)
from src.schemas import AgentContext, ExecutionPlan, ExecutionRun, ExecutedAction
from src.schemas.enums import ActionType, RouteName
from src.tools import (
    execute_documentation_lookup,
    execute_customer_lookup,
    execute_invoice_lookup,
    execute_order_lookup,
    execute_pricing_lookup,
    execute_shipping_lookup,
    execute_product_lookup,
    execute_technical_lookup,
)


def _execute_customization_intake(action, agent_input: Dict[str, Any]) -> ExecutedAction:
    output = {
        "intake_mode": "derived",
        "query": agent_input.get("query", ""),
        "open_slots": agent_input.get("open_slots", {}),
        "missing_information": agent_input.get("missing_information", []),
    }
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status="completed",
        summary="Derived a customization intake summary from the parsed request.",
        output=output,
    )


def _execute_summary(action, agent_input: Dict[str, Any]) -> ExecutedAction:
    output = {
        "summary_mode": "derived",
        "query": agent_input.get("query", ""),
        "primary_intent": agent_input.get("context", {}).get("primary_intent"),
        "risk_level": agent_input.get("context", {}).get("risk_level"),
    }
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status="completed",
        summary="Prepared an internal summary payload from the current request context.",
        output=output,
    )


def _execute_deferred(action) -> ExecutedAction:
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status="deferred",
        summary=action.description,
        output=action.metadata,
    )


def _execute_default(action) -> ExecutedAction:
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status="planned",
        summary=action.description or action.title,
        output=action.metadata,
    )


def execute_plan(agent_input: AgentContext, execution_plan: ExecutionPlan) -> ExecutionRun:
    agent_input_data = agent_input.model_dump(mode="json")
    primary_route = execution_plan.primary_route

    if primary_route == RouteName.COMMERCIAL_AGENT:
        executed_actions = execute_commercial_agent(agent_input_data, execution_plan)
        overall_status = "completed" if any(action.status == "completed" for action in executed_actions) else "planned"
        return ExecutionRun(
            plan_goal=execution_plan.plan_goal,
            overall_status=overall_status,
            executed_actions=executed_actions,
        )

    if primary_route == RouteName.OPERATIONAL_AGENT:
        executed_actions = execute_operational_agent(agent_input_data, execution_plan)
        overall_status = "completed" if any(action.status == "completed" for action in executed_actions) else "planned"
        return ExecutionRun(
            plan_goal=execution_plan.plan_goal,
            overall_status=overall_status,
            executed_actions=executed_actions,
        )

    if primary_route == RouteName.WORKFLOW_AGENT:
        executed_actions = execute_workflow_agent(agent_input_data, execution_plan)
        return ExecutionRun(
            plan_goal=execution_plan.plan_goal,
            overall_status="completed",
            executed_actions=executed_actions,
        )

    executed_actions: list[ExecutedAction] = []

    for action in execution_plan.actions:
        if action.action_type == ActionType.LOOKUP_PRICE:
            executed = execute_pricing_lookup(action, agent_input_data)
        elif action.action_type == ActionType.RETRIEVE_TECHNICAL_KNOWLEDGE:
            executed = execute_technical_lookup(action, agent_input_data)
        elif action.action_type == ActionType.LOOKUP_DOCUMENT:
            executed = execute_documentation_lookup(action, agent_input_data)
        elif action.action_type == ActionType.LOOKUP_CUSTOMER:
            executed = execute_customer_lookup(action, agent_input_data)
        elif action.action_type == ActionType.LOOKUP_INVOICE:
            executed = execute_invoice_lookup(action, agent_input_data)
        elif action.action_type == ActionType.LOOKUP_ORDER:
            executed = execute_order_lookup(action, agent_input_data)
        elif action.action_type == ActionType.LOOKUP_SHIPPING:
            executed = execute_shipping_lookup(action, agent_input_data)
        elif action.action_type == ActionType.LOOKUP_CATALOG_PRODUCT:
            executed = execute_product_lookup(action, agent_input_data)
        elif action.action_type == ActionType.PREPARE_CUSTOMIZATION_INTAKE:
            executed = _execute_customization_intake(action, agent_input_data)
        elif action.action_type in {ActionType.SUMMARIZE_CASE, ActionType.DRAFT_INTERNAL_SUMMARY, ActionType.DRAFT_REPLY}:
            executed = _execute_summary(action, agent_input_data)
        elif action.action_type in {ActionType.ESCALATE_TO_HUMAN, ActionType.RECORD_SECONDARY_FOLLOWUP, ActionType.CLARIFICATION_REQUEST}:
            executed = _execute_deferred(action)
        else:
            executed = _execute_default(action)
        executed_actions.append(executed)

    if not executed_actions:
        overall_status = "empty"
    elif any(action.status in {"mocked", "blocked"} for action in executed_actions):
        overall_status = "partial"
    elif all(action.status == "completed" for action in executed_actions):
        overall_status = "completed"
    else:
        overall_status = "planned"

    return ExecutionRun(
        plan_goal=execution_plan.plan_goal,
        overall_status=overall_status,
        executed_actions=executed_actions,
    )
