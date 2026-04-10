from __future__ import annotations

from src.catalog.service import lookup_catalog_products
from src.tools.result_builders import empty_result, error_result, ok_result, partial_result
from src.tools.models import ToolRequest, ToolResult

from .request_mapper import build_catalog_lookup_params


def execute_catalog_lookup(request: ToolRequest) -> ToolResult:
    params = build_catalog_lookup_params(request)
    output = lookup_catalog_products(**params)
    matches = output.get("matches", [])
    match_status = output.get("match_status")

    facts = {
        "query": request.query,
        "match_status": match_status or "",
        "matches": matches,
        "match_count": len(matches),
    }

    if matches:
        return ok_result(
            tool_name=request.tool_name,
            primary_records=matches,
            structured_facts=facts,
            debug_info={"catalog_params": params},
        )
    if match_status in {"driver_missing", "connection_failed"}:
        return partial_result(
            tool_name=request.tool_name,
            errors=["Catalog backend is unavailable."],
            structured_facts=facts,
            debug_info={"catalog_params": params, "catalog_output": output},
        )
    if match_status == "error":
        return error_result(
            tool_name=request.tool_name,
            error="Catalog lookup failed.",
            debug_info={"catalog_params": params, "catalog_output": output},
        )
    return empty_result(
        tool_name=request.tool_name,
        structured_facts=facts,
        debug_info={"catalog_params": params},
    )
