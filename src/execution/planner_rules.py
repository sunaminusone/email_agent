from __future__ import annotations

from src.execution.models import ExecutionMode, ToolCallRole


PRIMARY_TOOL_BY_OBJECT_TYPE = {
    "product": "catalog_lookup_tool",
    "service": "technical_rag_tool",
    "scientific_target": "technical_rag_tool",
    "document": "document_lookup_tool",
    "order": "order_lookup_tool",
    "shipment": "shipping_lookup_tool",
    "invoice": "invoice_lookup_tool",
    "customer": "customer_lookup_tool",
}


PARALLEL_SAFE_TOOLS = {
    "document_lookup_tool",
    "shipping_lookup_tool",
}


SEQUENTIAL_DEPENDENCIES = {
    ("catalog_lookup_tool", "technical_rag_tool"): ["catalog_lookup_tool"],
}


def infer_execution_mode(selected_tools: list[str]) -> ExecutionMode:
    if len(selected_tools) <= 1:
        return "single"
    if len(selected_tools) == 2 and tuple(selected_tools) in SEQUENTIAL_DEPENDENCIES:
        return "sequential"
    return "parallel"


def role_for_tool(tool_name: str, primary_tool_name: str | None) -> ToolCallRole:
    return "primary" if tool_name == primary_tool_name else "supporting"


def primary_tool_for_intent(intent) -> str | None:
    primary_object = intent.primary_object
    if primary_object is None:
        return intent.selected_tools[0] if intent.selected_tools else None
    preferred = PRIMARY_TOOL_BY_OBJECT_TYPE.get(primary_object.object_type)
    if preferred in intent.selected_tools:
        return preferred
    return intent.selected_tools[0] if intent.selected_tools else None


def depends_on(tool_name: str, selected_tools: list[str]) -> list[str]:
    if not selected_tools:
        return []
    key = tuple(selected_tools[:2]) if len(selected_tools) >= 2 else ()
    if key in SEQUENTIAL_DEPENDENCIES and tool_name == selected_tools[-1]:
        return list(SEQUENTIAL_DEPENDENCIES[key])
    return []


def can_run_in_parallel(tool_name: str, execution_mode: ExecutionMode, dependencies: list[str]) -> bool:
    if execution_mode != "parallel":
        return False
    if dependencies:
        return False
    return tool_name in PARALLEL_SAFE_TOOLS


def merge_policy_for_mode(execution_mode: ExecutionMode, selected_tools: list[str]) -> str:
    if not selected_tools:
        return "no_merge"
    if execution_mode == "single":
        return "single_source"
    if execution_mode == "sequential":
        return "primary_with_dependency_context"
    return "primary_with_supporting_context"
