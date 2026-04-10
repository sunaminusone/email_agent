from __future__ import annotations

from typing import Any

from src.tools.models import ToolResult
from src.tools.types import DEFAULT_TOOL_STATUS, ToolStatus


def build_tool_result(
    *,
    tool_name: str,
    status: ToolStatus = DEFAULT_TOOL_STATUS,
    primary_records: list[dict[str, Any]] | None = None,
    supporting_records: list[dict[str, Any]] | None = None,
    structured_facts: dict[str, Any] | None = None,
    unstructured_snippets: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    errors: list[str] | None = None,
    debug_info: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        status=status,
        primary_records=primary_records or [],
        supporting_records=supporting_records or [],
        structured_facts=structured_facts or {},
        unstructured_snippets=unstructured_snippets or [],
        artifacts=artifacts or [],
        errors=errors or [],
        debug_info=debug_info or {},
    )


def ok_result(*, tool_name: str, **kwargs: Any) -> ToolResult:
    return build_tool_result(tool_name=tool_name, status="ok", **kwargs)


def partial_result(*, tool_name: str, errors: list[str] | None = None, **kwargs: Any) -> ToolResult:
    return build_tool_result(tool_name=tool_name, status="partial", errors=errors, **kwargs)


def empty_result(*, tool_name: str, **kwargs: Any) -> ToolResult:
    return build_tool_result(tool_name=tool_name, status="empty", **kwargs)


def error_result(*, tool_name: str, error: str, debug_info: dict[str, Any] | None = None) -> ToolResult:
    merged_debug = dict(debug_info or {})
    merged_debug.setdefault("error_result", True)
    return build_tool_result(
        tool_name=tool_name,
        status="error",
        errors=[error],
        debug_info=merged_debug,
    )
