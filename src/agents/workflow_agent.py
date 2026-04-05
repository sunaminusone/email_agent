from typing import Any, Dict, List

from src.agents.utils import make_agent_draft_action
from src.schemas import ExecutedAction, ExecutionPlan, PlannedAction
from src.schemas.enums import ActionType


def _planned(action_id: str, action_type: str, title: str) -> PlannedAction:
    return PlannedAction(action_id=action_id, action_type=action_type, title=title, description=title)


def _execute_customization_intake(action, agent_input: Dict[str, Any]) -> ExecutedAction:
    output = {
        "workflow_mode": "customization_intake",
        "query": agent_input.get("query", ""),
        "open_slots": agent_input.get("open_slots", {}),
        "missing_information": agent_input.get("missing_information", []),
        "business_line": agent_input.get("routing_debug", {}).get("business_line", ""),
    }
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status="completed",
        summary="Prepared workflow intake details from the parsed request.",
        output=output,
    )


def execute_workflow_agent(agent_input: Dict[str, Any], execution_plan: ExecutionPlan) -> List[ExecutedAction]:
    intake_action = _planned("workflow-intake", ActionType.PREPARE_CUSTOMIZATION_INTAKE, "Workflow intake")
    intake_result = _execute_customization_intake(intake_action, agent_input)
    draft_result = make_agent_draft_action(
        "workflow-draft",
        "Workflow agent prepared the current intake state and next-step response.",
        {
            "agent": "workflow_agent",
            "workflow_type": "customization",
            "missing_information": agent_input.get("missing_information", []),
        },
    )
    return [intake_result, draft_result]
