from __future__ import annotations

from typing import Any

from src.schemas import ParsedResult, ReferenceResolution, TurnResolution
from src.strategies import (
    classify_identifier_candidates,
    strip_identifier_missing_information,
)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def _looks_like_product_confirmation(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    return any(
        phrase in normalized
        for phrase in [
            "it's a product",
            "it is a product",
            "its a product",
            "product",
            "catalog",
            "catalog number",
            "product number",
        ]
    )


def _looks_like_invoice_confirmation(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    return any(
        phrase in normalized
        for phrase in [
            "it's an invoice",
            "it is an invoice",
            "invoice",
            "billing record",
            "bill",
        ]
    )


def _looks_like_order_confirmation(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    return any(
        phrase in normalized
        for phrase in [
            "it's an order",
            "it is an order",
            "order",
            "purchase order",
            "po",
        ]
    )


def _build_identifier_follow_up(ambiguous_identifiers: list[str]) -> list[str]:
    if not ambiguous_identifiers:
        return []
    if len(ambiguous_identifiers) == 1:
        return [f"Please confirm whether {ambiguous_identifiers[0]} is a product/catalog number or an invoice/order number."]
    identifier_text = ", ".join(ambiguous_identifiers)
    return [f"Please confirm whether these identifiers refer to product/catalog numbers or invoice/order numbers: {identifier_text}."]


def merge_routing_memory_with_turn_resolution(routing_memory, turn_resolution: TurnResolution):
    continuity_mode = routing_memory.continuity_mode
    if turn_resolution.turn_type in {"fresh_request", "new_request"}:
        continuity_mode = "fresh_request"
    elif turn_resolution.turn_type == "clarification_answer":
        continuity_mode = "clarification_reply"
    elif turn_resolution.turn_type == "follow_up":
        continuity_mode = "follow_up"
    elif turn_resolution.turn_type == "route_continuation":
        continuity_mode = "route_continuation"

    return routing_memory.model_copy(
        update={
            "continuity_mode": continuity_mode,
            "continuity_confidence": turn_resolution.confidence or routing_memory.continuity_confidence,
            "should_stick_to_active_route": turn_resolution.should_reuse_active_route,
            "should_resume_pending_route": turn_resolution.should_resume_pending_route,
            "turn_resolution": turn_resolution,
            "state_reason": turn_resolution.reason or routing_memory.state_reason,
        }
    )


def apply_turn_resolution(
    parsed: ParsedResult,
    turn_resolution: TurnResolution,
) -> ParsedResult:
    if not turn_resolution.payload_usable or not turn_resolution.resolved_identifier:
        return parsed

    resolved_identifier = turn_resolution.resolved_identifier
    resolved_type = turn_resolution.resolved_identifier_type

    if resolved_type == "catalog_number" and not parsed.entities.catalog_numbers:
        request_flag_updates: dict[str, Any] = {}
        if not (
            parsed.request_flags.needs_price
            or parsed.request_flags.needs_quote
            or parsed.request_flags.needs_documentation
            or parsed.request_flags.needs_availability
        ):
            request_flag_updates["needs_availability"] = True
        if turn_resolution.resolved_user_goal == "request_documentation":
            request_flag_updates["needs_documentation"] = True
        if turn_resolution.resolved_user_goal == "request_pricing":
            request_flag_updates["needs_price"] = True
            request_flag_updates["needs_quote"] = True
        if turn_resolution.resolved_user_goal == "request_timeline":
            request_flag_updates["needs_timeline"] = True
        return parsed.model_copy(
            update={
                "entities": parsed.entities.model_copy(
                    update={
                        "catalog_numbers": _dedupe_preserve_order([*parsed.entities.catalog_numbers, resolved_identifier]),
                    }
                ),
                "missing_information": strip_identifier_missing_information(parsed.missing_information),
                "request_flags": parsed.request_flags.model_copy(update=request_flag_updates),
            }
        )

    if resolved_type in {"invoice_number", "order_number"} and not parsed.entities.order_numbers:
        request_flag_updates = {"needs_invoice": True} if resolved_type == "invoice_number" else {"needs_order_status": True}
        return parsed.model_copy(
            update={
                "entities": parsed.entities.model_copy(
                    update={
                        "order_numbers": _dedupe_preserve_order([*parsed.entities.order_numbers, resolved_identifier]),
                    }
                ),
                "missing_information": strip_identifier_missing_information(parsed.missing_information),
                "request_flags": parsed.request_flags.model_copy(update=request_flag_updates),
            }
        )

    return parsed


def apply_reference_resolution(
    parsed: ParsedResult,
    reference_resolution: ReferenceResolution,
) -> ParsedResult:
    if reference_resolution.resolution_mode not in {
        "other_recent_entity",
        "indexed_recent_entity",
        "previous_recent_entity",
        "entity_text_match",
        "all_recent_entities",
    }:
        return parsed

    resolved_identifiers = _dedupe_preserve_order(
        reference_resolution.resolved_identifiers
        or ([reference_resolution.resolved_identifier] if reference_resolution.resolved_identifier else [])
    )
    if not resolved_identifiers or not reference_resolution.resolved_identifier_type:
        return parsed

    if reference_resolution.resolved_identifier_type == "catalog_number":
        return parsed.model_copy(
            update={
                "entities": parsed.entities.model_copy(
                    update={
                        "catalog_numbers": resolved_identifiers,
                    }
                ),
                "missing_information": strip_identifier_missing_information(parsed.missing_information),
            }
        )

    if reference_resolution.resolved_identifier_type in {"invoice_number", "order_number"}:
        return parsed.model_copy(
            update={
                "entities": parsed.entities.model_copy(
                    update={
                        "order_numbers": resolved_identifiers,
                    }
                ),
                "missing_information": strip_identifier_missing_information(parsed.missing_information),
            }
        )

    return parsed


def resolve_identifier_from_routing_memory(parsed: ParsedResult, original_query: str, routing_memory) -> dict[str, Any]:
    pending_identifiers = list(routing_memory.pending_identifiers or [])
    if not pending_identifiers:
        return {"parsed": parsed, "ambiguous_identifiers": []}

    product_confirmation = _looks_like_product_confirmation(original_query)
    invoice_confirmation = _looks_like_invoice_confirmation(original_query)
    order_confirmation = _looks_like_order_confirmation(original_query)
    operational_confirmation = invoice_confirmation or order_confirmation

    if product_confirmation and not operational_confirmation:
        updated_catalog_numbers = _dedupe_preserve_order([*parsed.entities.catalog_numbers, *pending_identifiers])
        request_flag_updates: dict[str, Any] = {}
        if not (
            parsed.request_flags.needs_price
            or parsed.request_flags.needs_quote
            or parsed.request_flags.needs_documentation
            or parsed.request_flags.needs_availability
        ):
            request_flag_updates["needs_availability"] = True
        enriched = parsed.model_copy(
            update={
                "entities": parsed.entities.model_copy(update={"catalog_numbers": updated_catalog_numbers}),
                "missing_information": strip_identifier_missing_information(parsed.missing_information),
                "request_flags": parsed.request_flags.model_copy(update=request_flag_updates),
            }
        )
        return {"parsed": enriched, "ambiguous_identifiers": []}

    if operational_confirmation and not product_confirmation:
        updated_order_numbers = _dedupe_preserve_order([*parsed.entities.order_numbers, *pending_identifiers])
        request_flag_updates = {"needs_invoice": True} if invoice_confirmation else {"needs_order_status": True}
        enriched = parsed.model_copy(
            update={
                "entities": parsed.entities.model_copy(update={"order_numbers": updated_order_numbers}),
                "missing_information": strip_identifier_missing_information(parsed.missing_information),
                "request_flags": parsed.request_flags.model_copy(update=request_flag_updates),
            }
        )
        return {"parsed": enriched, "ambiguous_identifiers": []}

    return {"parsed": parsed, "ambiguous_identifiers": pending_identifiers}


def enrich_parsed_result_with_identifier_fallback(parsed: ParsedResult, original_query: str) -> dict[str, Any]:
    identifier_signals = classify_identifier_candidates(original_query)
    catalog_numbers = identifier_signals["catalog_numbers"]
    order_numbers = identifier_signals["order_numbers"]
    ambiguous_identifiers = identifier_signals["ambiguous_identifiers"]

    updated_catalog_numbers = _dedupe_preserve_order([*parsed.entities.catalog_numbers, *catalog_numbers])
    updated_order_numbers = _dedupe_preserve_order([*parsed.entities.order_numbers, *order_numbers])

    updated_missing_information = parsed.missing_information
    if updated_catalog_numbers or updated_order_numbers:
        updated_missing_information = strip_identifier_missing_information(updated_missing_information)
    if ambiguous_identifiers:
        updated_missing_information = _dedupe_preserve_order([
            *strip_identifier_missing_information(updated_missing_information),
            *_build_identifier_follow_up(ambiguous_identifiers),
        ])

    request_flag_updates: dict[str, Any] = {}
    if updated_catalog_numbers and not (
        parsed.request_flags.needs_price
        or parsed.request_flags.needs_quote
        or parsed.request_flags.needs_documentation
        or parsed.request_flags.needs_availability
    ):
        request_flag_updates["needs_availability"] = True
    if identifier_signals["invoice_context"]:
        request_flag_updates["needs_invoice"] = True
    elif identifier_signals["order_context"] and not parsed.request_flags.needs_order_status:
        request_flag_updates["needs_order_status"] = True
    if identifier_signals["documentation_context"] and not parsed.request_flags.needs_documentation:
        request_flag_updates["needs_documentation"] = True
    if identifier_signals["pricing_context"]:
        if not parsed.request_flags.needs_price:
            request_flag_updates["needs_price"] = True
        if not parsed.request_flags.needs_quote:
            request_flag_updates["needs_quote"] = True
    if identifier_signals["timeline_context"] and not parsed.request_flags.needs_timeline:
        request_flag_updates["needs_timeline"] = True

    enriched_parsed = parsed.model_copy(
        update={
            "entities": parsed.entities.model_copy(
                update={
                    "catalog_numbers": updated_catalog_numbers,
                    "order_numbers": updated_order_numbers,
                }
            ),
            "missing_information": updated_missing_information,
            "request_flags": parsed.request_flags.model_copy(update=request_flag_updates),
        }
    )

    return {
        "parsed": enriched_parsed,
        "ambiguous_identifiers": ambiguous_identifiers,
    }
