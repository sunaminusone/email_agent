from __future__ import annotations

from src.tools.errors import ToolExecutionError, UnknownToolError
from src.tools.models import ToolRequest, ToolResult
from src.tools.registry import get_tool_executor
from src.tools.result_builders import error_result


def dispatch_tool(request: ToolRequest) -> ToolResult:
    executor = get_tool_executor(request.tool_name)
    try:
        return executor(request)
    except Exception as exc:
        raise ToolExecutionError(
            f"Tool '{request.tool_name}' failed during execution: {exc}"
        ) from exc


def safe_dispatch_tool(request: ToolRequest) -> ToolResult:
    try:
        return dispatch_tool(request)
    except UnknownToolError as exc:
        return error_result(
            tool_name=request.tool_name,
            error=str(exc),
            debug_info={"dispatcher_error": True, "unregistered_tool": True},
        )
    except Exception as exc:
        return error_result(
            tool_name=request.tool_name,
            error=str(exc),
            debug_info={"dispatcher_error": True},
        )
