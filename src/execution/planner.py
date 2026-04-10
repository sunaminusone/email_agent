from __future__ import annotations

from src.execution.models import ExecutionPlan
from src.execution.planner_rules import (
    can_run_in_parallel,
    depends_on,
    infer_execution_mode,
    merge_policy_for_mode,
    primary_tool_for_intent,
    role_for_tool,
)
from src.execution.requests import attach_requests
from src.routing.models import ExecutionIntent


def plan_execution(intent: ExecutionIntent) -> ExecutionPlan:
    execution_mode = infer_execution_mode(list(intent.selected_tools))
    primary_tool_name = primary_tool_for_intent(intent)

    draft_calls: list[dict] = []
    for index, tool_name in enumerate(intent.selected_tools, start=1):
        dependencies = depends_on(tool_name, list(intent.selected_tools))
        draft_calls.append(
            {
                "call_id": f"call-{index}",
                "tool_name": tool_name,
                "role": role_for_tool(tool_name, primary_tool_name),
                "priority": index,
                "can_run_in_parallel": can_run_in_parallel(tool_name, execution_mode, dependencies),
                "depends_on": dependencies,
            }
        )

    planned_calls = attach_requests(intent, draft_calls)
    merge_policy = merge_policy_for_mode(execution_mode, list(intent.selected_tools))
    reason = _planning_reason(intent, execution_mode, primary_tool_name)

    return ExecutionPlan(
        intent=intent,
        planned_calls=planned_calls,
        execution_mode=execution_mode,
        merge_policy=merge_policy,
        reason=reason,
    )


def _planning_reason(intent: ExecutionIntent, execution_mode: str, primary_tool_name: str | None) -> str:
    if intent.handoff_required:
        return "Execution planning remains empty because routing requested handoff."
    if intent.needs_clarification:
        return "Execution planning remains empty because routing requested clarification."
    if not intent.selected_tools:
        return "No execution plan was created because routing selected no tools."
    if execution_mode == "single":
        return f"Execution uses a single tool plan anchored on {primary_tool_name or intent.selected_tools[0]}."
    if execution_mode == "sequential":
        return "Execution uses a sequential plan because downstream context depends on an earlier tool result."
    return "Execution uses a parallel plan because the selected tools can run independently."
