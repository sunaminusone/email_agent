from __future__ import annotations

from src.executor.models import ExecutedToolCall, MergedResults


def merge_execution_results(executed_calls: list[ExecutedToolCall]) -> tuple[MergedResults, str, str]:
    primary_facts: dict[str, object] = {}
    supporting_facts: dict[str, object] = {}
    snippets: list[dict] = []
    artifacts: list[dict] = []

    for call in executed_calls:
        result = call.result
        if result is None:
            continue

        target = primary_facts if call.role == "primary" else supporting_facts
        target[call.tool_name] = result.structured_facts
        snippets.extend(result.unstructured_snippets)
        artifacts.extend(result.artifacts)

    merged = MergedResults(
        primary_facts=primary_facts,
        supporting_facts=supporting_facts,
        snippets=snippets,
        artifacts=artifacts,
    )
    final_status = final_status_for_calls([call.status for call in executed_calls])
    reason = _merge_reason(executed_calls, final_status)
    return merged, final_status, reason


def _merge_reason(executed_calls: list[ExecutedToolCall], final_status: str) -> str:
    if not executed_calls:
        return "No tool calls were executed."
    if final_status == "error":
        return "Execution completed with at least one tool error."
    if final_status == "partial":
        return "Execution completed with partial tool results."
    if final_status == "ok":
        return "Execution completed successfully."
    return "Execution produced no grounded tool output."


def final_status_for_calls(statuses: list[str]) -> str:
    if not statuses:
        return "empty"
    if any(status == "error" for status in statuses):
        return "error"
    if any(status == "partial" for status in statuses):
        return "partial"
    if any(status == "ok" for status in statuses):
        return "ok"
    return "empty"
