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

    pg_records = [_pricing_record(match) for match in matches]
    primary_object = request.primary_object
    is_product_query = primary_object is not None and primary_object.object_type == "product"
    # Skip the flyer Chroma path only when the customer gave us a real,
    # DB-confirmed catalog # (resolved through lookup_product_by_catalog_no,
    # not just regex-shaped). For those queries the flyer would only add
    # unrelated service plans (e.g. CAR-T flyer chunks for a #20338
    # lookup) since flyer returns top-k nearest-neighbour pricing chunks
    # with no relevance threshold.
    # For other product queries (named-product or product-name strings
    # that the deterministic regex misclassified as catalog_no) we keep
    # flyer ranked AFTER catalog so service alternatives stay visible —
    # e.g. "Price for CAR-T?" still surfaces CAR-T service plans below
    # the catalog products. The 8-record prompt cap downstream naturally
    # demotes weak flyer chunks when catalog has many high-signal hits.
    is_resolved_catalog_no = (
        is_product_query
        and primary_object is not None
        and primary_object.identifier_type == "catalog_no"
        and primary_object.metadata.get("match_strategy") != "unknown_catalog_no"
    )
    # Hand the upstream-resolved service name to flyer ranking when the
    # parser+resolver settled on a service. flyer_pricing validates this
    # against the known Chroma service_name set and falls back to its
    # own keyword detection on miss, so passing it is always safe.
    preferred_service_name = (
        primary_object.canonical_value
        if primary_object is not None
        and primary_object.object_type == "service"
        and primary_object.canonical_value
        else None
    )
    if is_resolved_catalog_no:
        flyer_records: list[dict[str, object]] = []
        pricing_records = pg_records
    elif is_product_query:
        flyer_records = lookup_flyer_pricing(
            query=request.query, top_k=3, preferred_service_name=preferred_service_name,
        )
        pricing_records = pg_records + flyer_records
    else:
        flyer_records = lookup_flyer_pricing(
            query=request.query, top_k=3, preferred_service_name=preferred_service_name,
        )
        pricing_records = flyer_records + pg_records

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
