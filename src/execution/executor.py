from __future__ import annotations

import time

from src.execution.merger import merge_execution_results
from src.execution.models import ExecutedToolCall, ExecutionPlan, ExecutionRun
from src.tools.dispatcher import safe_dispatch_tool


def execute_plan(plan: ExecutionPlan) -> ExecutionRun:
    executed_calls: list[ExecutedToolCall] = []

    for planned_call in plan.planned_calls:
        started = time.perf_counter()
        result = safe_dispatch_tool(planned_call.request)
        latency_ms = int((time.perf_counter() - started) * 1000)
        executed_calls.append(
            ExecutedToolCall(
                call_id=planned_call.call_id,
                tool_name=planned_call.tool_name,
                role=planned_call.role,
                status=result.status,
                request=planned_call.request,
                result=result,
                latency_ms=latency_ms,
                error=result.errors[0] if result.errors else "",
            )
        )

    merged_results, final_status, reason = merge_execution_results(executed_calls)
    return ExecutionRun(
        intent=plan.intent,
        plan=plan,
        executed_calls=executed_calls,
        merged_results=merged_results,
        final_status=final_status,
        reason=reason,
    )
