from typing import Any, Dict, List

from src.catalog.service import lookup_catalog_products
from src.schemas import ExecutedAction


def _joined(values: List[str]) -> str:
    cleaned = [value for value in values if value]
    return ", ".join(cleaned)


def _normalized_business_line_hint(routing_debug: Dict[str, Any]) -> str:
    hint = (routing_debug.get("business_line") or "").strip()
    if hint in {"", "unknown", "cross_line"}:
        return ""
    return hint


def execute_pricing_lookup(action, agent_input: Dict[str, Any]) -> ExecutedAction:
    product_lookup_keys = agent_input.get("product_lookup_keys", {})
    entities = agent_input.get("entities", {})
    routing_debug = agent_input.get("routing_debug", {})
    business_line_hint = _normalized_business_line_hint(routing_debug)
    output = lookup_catalog_products(
        query=agent_input.get("effective_query") or agent_input.get("query", ""),
        catalog_numbers=product_lookup_keys.get("catalog_numbers", []),
        product_names=product_lookup_keys.get("product_names", []),
        service_names=product_lookup_keys.get("service_names", []),
        targets=product_lookup_keys.get("targets", []) or entities.get("targets", []),
        applications=product_lookup_keys.get("applications", []),
        species=product_lookup_keys.get("species", []),
        format_or_size=product_lookup_keys.get("format_or_size", ""),
        business_line_hint=business_line_hint,
        top_k=10,
    )
    output["destination"] = product_lookup_keys.get("destination")
    matches = output.get("matches", [])
    product_reference = (
        _joined(product_lookup_keys.get("catalog_numbers", []))
        or _joined(product_lookup_keys.get("product_names", []))
        or _joined(product_lookup_keys.get("service_names", []))
        or "the requested product"
    )
    match_status = output.get("match_status")
    if matches:
        top_match = matches[0]
        summary = (
            f"Matched {len(matches)} pricing record(s) for {product_reference}. "
            f"Top hit: {top_match.get('catalog_no') or top_match.get('name') or 'unknown product'}."
        )
        status = "completed"
    elif match_status in {"driver_missing", "connection_failed"}:
        summary = "Product pricing backend is unavailable."
        status = "blocked"
    else:
        summary = f"No pricing match was found for {product_reference}."
        status = "not_found"
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status=status,
        summary=summary,
        output=output,
    )


def execute_product_lookup(action, agent_input: Dict[str, Any]) -> ExecutedAction:
    product_lookup_keys = agent_input.get("product_lookup_keys", {})
    entities = agent_input.get("entities", {})
    routing_debug = agent_input.get("routing_debug", {})
    business_line_hint = _normalized_business_line_hint(routing_debug)
    output = lookup_catalog_products(
        query=agent_input.get("effective_query") or agent_input.get("query", ""),
        catalog_numbers=product_lookup_keys.get("catalog_numbers", []),
        product_names=product_lookup_keys.get("product_names", []),
        service_names=product_lookup_keys.get("service_names", []),
        targets=product_lookup_keys.get("targets", []) or entities.get("targets", []),
        applications=product_lookup_keys.get("applications", []),
        species=product_lookup_keys.get("species", []),
        format_or_size=product_lookup_keys.get("format_or_size", ""),
        business_line_hint=business_line_hint,
        top_k=10,
    )
    if output.get("matches"):
        status = "completed"
        summary = f"Matched {len(output['matches'])} product record(s)."
    elif output.get("match_status") in {"driver_missing", "connection_failed"}:
        status = "blocked"
        summary = "Product lookup backend is unavailable."
    else:
        status = "not_found"
        summary = "No matching products were found."
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status=status,
        summary=summary,
        output=output,
    )
