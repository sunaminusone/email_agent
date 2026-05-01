from __future__ import annotations

from src.catalog.service import lookup_catalog_products
from src.rag.flyer_pricing import lookup_flyer_pricing
from src.tools.models import ToolRequest, ToolResult
from src.tools.result_builders import empty_result, error_result, ok_result, partial_result

from .request_mapper import build_catalog_lookup_params


def execute_pricing_lookup_tool(request: ToolRequest) -> ToolResult:
    params = build_catalog_lookup_params(request)
    output = lookup_catalog_products(**params)
    matches = output.get("matches", [])
    match_status = output.get("match_status")

    pricing_records = [_pricing_record(match) for match in matches]
    flyer_records = lookup_flyer_pricing(query=request.query, top_k=3)
    pricing_records.extend(flyer_records)

    facts = {
        "query": request.query,
        "match_status": match_status or "",
        "pricing_records": pricing_records,
        "match_count": len(pricing_records),
        "pg_match_count": len(matches),
        "flyer_match_count": len(flyer_records),
    }

    if pricing_records:
        return ok_result(
            tool_name=request.tool_name,
            primary_records=pricing_records,
            supporting_records=matches,
            structured_facts=facts,
            debug_info={"catalog_params": params},
        )
    if match_status in {"driver_missing", "connection_failed"}:
        return partial_result(
            tool_name=request.tool_name,
            errors=["Pricing backend is unavailable."],
            structured_facts=facts,
            debug_info={"catalog_params": params, "catalog_output": output},
        )
    if match_status == "error":
        return error_result(
            tool_name=request.tool_name,
            error="Pricing lookup failed.",
            debug_info={"catalog_params": params, "catalog_output": output},
        )
    return empty_result(
        tool_name=request.tool_name,
        structured_facts=facts,
        debug_info={"catalog_params": params},
    )


def _pricing_record(match: dict[str, object]) -> dict[str, object]:
    return {
        "catalog_no": match.get("catalog_no"),
        "name": match.get("name"),
        "price": match.get("price"),
        "currency": match.get("currency"),
        "lead_time_text": match.get("lead_time_text"),
        "business_line": match.get("business_line"),
    }
