from __future__ import annotations

from src.execution.models import ExecutedToolCall
from src.execution.status import final_status_for_calls


def merge_execution_results(executed_calls: list[ExecutedToolCall]) -> tuple[dict[str, object], str, str]:
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

    merged_results = {
        "primary_facts": primary_facts,
        "supporting_facts": supporting_facts,
        "snippets": snippets,
        "artifacts": artifacts,
    }
    final_status = final_status_for_calls([call.status for call in executed_calls])
    reason = _merge_reason(executed_calls, final_status)
    return merged_results, final_status, reason


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
