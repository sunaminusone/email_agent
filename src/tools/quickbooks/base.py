from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.integrations.quickbooks import QuickBooksClient, QuickBooksConfigError
from src.tools.models import ToolRequest, ToolResult
from src.tools.result_builders import empty_result, error_result, ok_result, partial_result


DEFAULT_NOT_CONFIGURED_STEP = "Set QB_CLIENT_ID, QB_CLIENT_SECRET, and QB_REDIRECT_URI in .env."
DEFAULT_NOT_CONNECTED_STEP = "Open /qb/connect in the browser and finish the QuickBooks OAuth consent flow."


def execute_quickbooks_tool(
    *,
    request: ToolRequest,
    lookup_mode: str,
    status_key: str,
    lookup_label: str,
    request_payload: dict[str, Any],
    perform_lookup: Callable[[QuickBooksClient], dict[str, Any]],
) -> ToolResult:
    client = QuickBooksClient()

    if not client.is_configured():
        facts = {
            "lookup_mode": lookup_mode,
            status_key: "not_configured",
            "next_step": DEFAULT_NOT_CONFIGURED_STEP,
            **request_payload,
        }
        return partial_result(
            tool_name=request.tool_name,
            errors=[f"QuickBooks {lookup_label} lookup is not configured."],
            structured_facts=facts,
            debug_info={"quickbooks_request": request_payload},
        )

    connection_status = client.get_connection_status()
    if not connection_status.get("connected"):
        facts = {
            "lookup_mode": lookup_mode,
            status_key: "not_connected",
            "next_step": DEFAULT_NOT_CONNECTED_STEP,
            **request_payload,
        }
        return partial_result(
            tool_name=request.tool_name,
            errors=[f"QuickBooks {lookup_label} lookup is not connected."],
            structured_facts=facts,
            debug_info={"quickbooks_request": request_payload, "connection_status": connection_status},
        )

    try:
        output = perform_lookup(client)
    except QuickBooksConfigError as exc:
        return error_result(
            tool_name=request.tool_name,
            error=f"QuickBooks {lookup_label} lookup could not start: {exc}",
            debug_info={"quickbooks_request": request_payload},
        )
    except Exception as exc:
        return error_result(
            tool_name=request.tool_name,
            error=f"QuickBooks returned an error during {lookup_label} lookup: {exc}",
            debug_info={"quickbooks_request": request_payload},
        )

    output["lookup_mode"] = lookup_mode
    output[status_key] = output.get("status")
    facts = {
        **output,
        "match_count": len(output.get("matches", [])),
    }
    matches = output.get("matches", [])

    if output.get("status") == "needs_input":
        return empty_result(
            tool_name=request.tool_name,
            structured_facts=facts,
            debug_info={"quickbooks_request": request_payload},
        )
    if matches:
        return ok_result(
            tool_name=request.tool_name,
            primary_records=matches,
            structured_facts=facts,
            debug_info={"quickbooks_request": request_payload},
        )
    if output.get("status") in {"completed", "not_found"}:
        return empty_result(
            tool_name=request.tool_name,
            structured_facts=facts,
            debug_info={"quickbooks_request": request_payload},
        )
    return partial_result(
        tool_name=request.tool_name,
        errors=[f"QuickBooks {lookup_label} lookup returned status '{output.get('status', '')}'."],
        structured_facts=facts,
        debug_info={"quickbooks_request": request_payload},
    )
