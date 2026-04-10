from __future__ import annotations

from src.execution.executor import execute_plan
from src.execution.models import ExecutionPlan, ExecutionRun
from src.execution.planner import plan_execution
from src.routing.models import ExecutionIntent


def build_execution_plan(intent: ExecutionIntent) -> ExecutionPlan:
    return plan_execution(intent)


def run_execution(intent: ExecutionIntent) -> ExecutionRun:
    return execute_plan(plan_execution(intent))


def run_execution_plan(plan: ExecutionPlan) -> ExecutionRun:
    return execute_plan(plan)
