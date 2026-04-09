from __future__ import annotations

from typing import Any

from src.conversation.context_scope import resolve_effective_scope
from src.responders.common import (
    requested_customer_fields,
    requested_invoice_fields,
    requested_order_fields,
    requested_shipping_fields,
)
from src.schemas import AtomicContentBlock, ResponseResolution


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _is_general_info_follow_up(payload: dict) -> bool:
    normalized_query = _normalize_text(payload["query"])
    info_markers = [
        "other information",
        "more information",
        "more info",
        "additional information",
        "additional info",
        "more details",
        "details",
        "tell me more",
        "anything else",
    ]
    return (
        payload["agent_input"].turn_resolution.turn_type in {"follow_up", "clarification_answer"}
        and any(marker in normalized_query for marker in info_markers)
    )


def _top_match(execution_run, action_type: str) -> dict[str, Any]:
    action = next((action for action in execution_run.executed_actions if action.action_type == action_type), None)
    matches = action.output.get("matches", []) if action else []
    return matches[0] if matches else {}


def _all_matches(execution_run, action_type: str) -> list[dict[str, Any]]:
    action = next((action for action in execution_run.executed_actions if action.action_type == action_type), None)
    matches = action.output.get("matches", []) if action else []
    return [match for match in matches if isinstance(match, dict)]


def _first_action(execution_run, action_type: str):
    return next((action for action in execution_run.executed_actions if action.action_type == action_type), None)


def _resolved_scope_block(payload: dict, product_matches: list[dict[str, Any]]) -> AtomicContentBlock | None:
    agent_input = payload["agent_input"]
    execution_run = payload["execution_run"]
    turn_type = agent_input.turn_resolution.turn_type
    prior_entity_kind = agent_input.routing_memory.session_payload.active_entity.entity_kind

    technical_action = _first_action(execution_run, "retrieve_technical_knowledge")
    technical_debug = technical_action.output.get("retrieval_debug", {}) if technical_action else {}
    technical_scope_type = str(technical_debug.get("effective_scope_type") or "").strip()
    technical_scope_name = str(technical_debug.get("effective_scope_name") or "").strip()
    technical_scope_source = str(technical_debug.get("effective_scope_source") or "").strip()

    if technical_scope_type and technical_scope_name:
        should_acknowledge = technical_scope_source == "active"
        acknowledgement_mode = "assumed" if technical_scope_source == "active" else "explicit"
        return AtomicContentBlock(
            kind="resolved_scope",
            payload={
                "scope_type": technical_scope_type,
                "scope_name": technical_scope_name,
                "scope_source": technical_scope_source,
                "catalog_no": "",
                "business_line": technical_action.output.get("business_line_hint", ""),
                "should_acknowledge": should_acknowledge,
                "acknowledgement_mode": acknowledgement_mode if should_acknowledge else "none",
            },
            text=f"Resolved scope: {technical_scope_type} {technical_scope_name} ({technical_scope_source or 'unknown source'}).",
        )

    effective_scope = resolve_effective_scope(
        {
            "query": agent_input.query,
            "original_query": agent_input.original_query,
            "effective_query": agent_input.effective_query,
            "context": {"primary_intent": agent_input.context.primary_intent},
            "entities": {
                "service_names": list(agent_input.entities.service_names),
                "product_names": list(agent_input.entities.product_names),
                "catalog_numbers": list(agent_input.entities.catalog_numbers),
                "targets": list(agent_input.entities.targets),
            },
            "product_lookup_keys": {
                "service_names": list(agent_input.product_lookup_keys.service_names),
                "product_names": list(agent_input.product_lookup_keys.product_names),
                "catalog_numbers": list(agent_input.product_lookup_keys.catalog_numbers),
                "targets": list(agent_input.product_lookup_keys.targets),
            },
            "active_service_name": agent_input.active_service_name,
            "active_product_name": agent_input.active_product_name,
            "active_target": agent_input.active_target,
            "session_payload": {
                "active_service_name": agent_input.session_payload.active_service_name,
                "active_product_name": agent_input.session_payload.active_product_name,
                "active_target": agent_input.session_payload.active_target,
                "active_entity": {"entity_kind": agent_input.session_payload.active_entity.entity_kind},
            },
            "routing_memory": {
                "should_stick_to_active_route": agent_input.routing_memory.should_stick_to_active_route,
                "session_payload": {
                    "active_entity": {
                        "entity_kind": agent_input.routing_memory.session_payload.active_entity.entity_kind,
                    }
                },
            },
            "turn_resolution": {"turn_type": turn_type},
        }
    )

    if product_matches:
        product_match = product_matches[0]
        current_turn_has_product_scope = bool(agent_input.entities.product_names or agent_input.entities.catalog_numbers)
        scope_source = "current" if current_turn_has_product_scope else ("active" if agent_input.active_product_name else "")
        should_acknowledge = bool(
            product_match.get("name")
            and prior_entity_kind
            and prior_entity_kind != "product"
            and turn_type in {"follow_up", "clarification_answer", "fresh_request", "new_request"}
        )
        acknowledgement_mode = "explicit" if current_turn_has_product_scope else "assumed"
        return AtomicContentBlock(
            kind="resolved_scope",
            payload={
                "scope_type": "product",
                "scope_name": product_match.get("name") or product_match.get("display_name") or "",
                "scope_source": scope_source,
                "catalog_no": product_match.get("catalog_no") or "",
                "business_line": product_match.get("business_line") or "",
                "should_acknowledge": should_acknowledge,
                "acknowledgement_mode": acknowledgement_mode if should_acknowledge else "none",
            },
            text=f"Resolved scope: product {product_match.get('catalog_no') or product_match.get('name') or 'unknown'}.",
        )

    if effective_scope.get("scope_type") and effective_scope.get("name"):
        should_acknowledge = effective_scope.get("source") == "active"
        acknowledgement_mode = "assumed" if effective_scope.get("source") == "active" else "explicit"
        return AtomicContentBlock(
            kind="resolved_scope",
            payload={
                "scope_type": effective_scope.get("scope_type", ""),
                "scope_name": effective_scope.get("name", ""),
                "scope_source": effective_scope.get("source", ""),
                "catalog_no": "",
                "business_line": agent_input.active_business_line or agent_input.routing_debug.business_line,
                "should_acknowledge": should_acknowledge,
                "acknowledgement_mode": acknowledgement_mode if should_acknowledge else "none",
            },
            text=f"Resolved scope: {effective_scope.get('scope_type', '')} {effective_scope.get('name', '')}.",
        )

    return None


def _product_identity_matches(execution_run) -> list[dict[str, Any]]:
    ordered_matches = [
        *_all_matches(execution_run, "lookup_catalog_product"),
        *_all_matches(execution_run, "lookup_price"),
    ]
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for match in ordered_matches:
        key = (
            str(match.get("catalog_no") or "").strip().lower(),
            str(match.get("name") or match.get("display_name") or "").strip().lower(),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(match)
    return deduped


def build_content_blocks(payload: dict) -> list[AtomicContentBlock]:
    execution_run = payload["execution_run"]
    response_resolution: ResponseResolution = payload["response_resolution"]
    content_priority = response_resolution.content_priority or ["summary"]

    product_matches = _product_identity_matches(execution_run)
    product_match = product_matches[0] if product_matches else {}
    document_match = _top_match(execution_run, "lookup_document")
    technical_match = _top_match(execution_run, "retrieve_technical_knowledge")
    invoice_match = _top_match(execution_run, "lookup_invoice")
    order_match = _top_match(execution_run, "lookup_order")
    shipping_match = _top_match(execution_run, "lookup_shipping")
    customer_match = _top_match(execution_run, "lookup_customer")
    price_action = _first_action(execution_run, "lookup_price")
    document_action = _first_action(execution_run, "lookup_document")
    workflow_action = next(
        (action for action in execution_run.executed_actions if action.action_type == "prepare_customization_intake"),
        None,
    )

    general_info_follow_up = _is_general_info_follow_up(payload)
    blocks: list[AtomicContentBlock] = []
    scope_block = _resolved_scope_block(payload, product_matches)
    if scope_block is not None:
        blocks.append(scope_block)

    for key in content_priority:
        if key == "product_identity" and product_matches:
            for match in product_matches:
                name = match.get("name") or match.get("display_name") or "unknown product"
                catalog_no = match.get("catalog_no") or "unknown"
                business_line = match.get("business_line") or "unknown"
                blocks.append(
                    AtomicContentBlock(
                        kind=key,
                        payload={
                            "product_name": name,
                            "catalog_no": catalog_no,
                            "business_line": business_line,
                            "general_info_follow_up": general_info_follow_up,
                        },
                        text=f"Matched product: {name} (ID: {catalog_no}), business line {business_line}.",
                    )
                )
        elif key == "price" and (price_action or product_match):
            price_source = _top_match(execution_run, "lookup_price") or product_match
            price = price_source.get("price_text") or price_source.get("price") or price_source.get("list_price")
            currency = price_source.get("currency") or "USD"
            price_status = (price_action.status if price_action else "") or (price_action.output.get("match_status", "") if price_action else "")
            blocks.append(
                AtomicContentBlock(
                    kind=key,
                    payload={
                        "amount": price,
                        "currency": currency,
                        "catalog_no": price_source.get("catalog_no") or "unknown",
                        "product_name": price_source.get("name") or price_source.get("display_name") or "unknown product",
                        "status": price_status or ("completed" if price else "unknown"),
                    },
                    text=(
                        f"Listed price: {price} {currency}."
                        if price
                        else f"Pricing status: {price_status or 'unknown'}."
                    ),
                )
            )
        elif key == "lead_time" and (price_action or product_match):
            lead_time_source = _top_match(execution_run, "lookup_price") or product_match
            lead_time = (
                lead_time_source.get("lead_time_text")
                or lead_time_source.get("lead_time")
                or lead_time_source.get("turnaround_time")
            )
            lead_time_status = (price_action.status if price_action else "") or (price_action.output.get("match_status", "") if price_action else "")
            blocks.append(
                AtomicContentBlock(
                    kind=key,
                    payload={
                        "lead_time": lead_time,
                        "catalog_no": lead_time_source.get("catalog_no") or "unknown",
                        "product_name": lead_time_source.get("name") or lead_time_source.get("display_name") or "unknown product",
                        "status": lead_time_status or ("completed" if lead_time else "unknown"),
                    },
                    text=(
                        f"Lead time: {lead_time}."
                        if lead_time
                        else f"Lead-time status: {lead_time_status or 'unknown'}."
                    ),
                )
            )
        elif key == "target_antigen" and product_match.get("target_antigen"):
            blocks.append(
                AtomicContentBlock(
                    kind=key,
                    payload={"target_antigen": product_match["target_antigen"]},
                    text=f"Target antigen: {product_match['target_antigen']}.",
                )
            )
        elif key == "application" and product_match.get("application_text"):
            blocks.append(
                AtomicContentBlock(
                    kind=key,
                    payload={"application_text": product_match["application_text"]},
                    text=f"Applications: {product_match['application_text']}.",
                )
            )
        elif key == "species_reactivity" and product_match.get("species_reactivity_text"):
            blocks.append(
                AtomicContentBlock(
                    kind=key,
                    payload={"species_reactivity_text": product_match["species_reactivity_text"]},
                    text=f"Species reactivity: {product_match['species_reactivity_text']}.",
                )
            )
        elif key == "documents" and document_action:
            blocks.append(
                AtomicContentBlock(
                    kind=key,
                    payload={
                        "file_name": document_match.get("file_name", ""),
                        "product_scope": document_match.get("product_scope", ""),
                        "document_url": document_match.get("document_url", ""),
                        "status": document_action.status or document_action.output.get("lookup_status", ""),
                        "requested_document_types": document_action.output.get("requested_document_types", []),
                        "found": bool(document_match),
                    },
                    text=(
                        f"Top document match: {document_match.get('file_name', 'unknown document')}."
                        if document_match
                        else "No matching document was found in the current document catalog."
                    ),
                )
            )
        elif key == "technical_context" and technical_match.get("content_preview"):
            blocks.append(
                AtomicContentBlock(
                    kind=key,
                    payload={
                        "content_preview": technical_match["content_preview"],
                        "file_name": technical_match.get("file_name", ""),
                        "business_line": technical_match.get("business_line", ""),
                    },
                    text=f"Technical evidence: {technical_match['content_preview']}",
                )
            )
        elif key == "invoice_status":
            invoice_action = next((action for action in execution_run.executed_actions if action.action_type == "lookup_invoice"), None)
            if invoice_action:
                blocks.append(
                    AtomicContentBlock(
                        kind=key,
                        payload={
                            "status": invoice_action.output.get("invoice_status", ""),
                            "requested_fields": sorted(requested_invoice_fields(payload["query"])),
                            "match": invoice_match,
                        },
                        text=f"Invoice lookup result: {invoice_match or invoice_action.output}.",
                    )
                )
        elif key == "order_status":
            order_action = next((action for action in execution_run.executed_actions if action.action_type == "lookup_order"), None)
            if order_action:
                blocks.append(
                    AtomicContentBlock(
                        kind=key,
                        payload={
                            "status": order_action.output.get("order_status", ""),
                            "requested_fields": sorted(requested_order_fields(payload["query"])),
                            "match": order_match,
                        },
                        text=f"Order lookup result: {order_match or order_action.output}.",
                    )
                )
        elif key == "shipping_status":
            shipping_action = next((action for action in execution_run.executed_actions if action.action_type == "lookup_shipping"), None)
            if shipping_action:
                blocks.append(
                    AtomicContentBlock(
                        kind=key,
                        payload={
                            "status": shipping_action.output.get("shipping_status", "") or shipping_action.output.get("status", ""),
                            "requested_fields": sorted(requested_shipping_fields(payload["query"])),
                            "match": shipping_match,
                        },
                        text=f"Shipping lookup result: {shipping_match or shipping_action.output}.",
                    )
                )
        elif key == "customer_profile":
            customer_action = next((action for action in execution_run.executed_actions if action.action_type == "lookup_customer"), None)
            if customer_action:
                blocks.append(
                    AtomicContentBlock(
                        kind=key,
                        payload={
                            "status": customer_action.output.get("customer_status", ""),
                            "requested_fields": sorted(requested_customer_fields(payload["query"])),
                            "match": customer_match,
                        },
                        text=f"Customer lookup result: {customer_match or customer_action.output}.",
                    )
                )
        elif key == "workflow_status":
            blocks.append(
                AtomicContentBlock(
                    kind=key,
                    payload={
                        "status": "active",
                        "workflow_mode": (workflow_action.output.get("workflow_mode") if workflow_action else "customization_intake"),
                        "business_line": (workflow_action.output.get("business_line") if workflow_action else payload["route"].business_line),
                        "missing_information": (workflow_action.output.get("missing_information") if workflow_action else []),
                    },
                    text="Workflow intake is active and ready to continue."
                    if not (workflow_action and workflow_action.output.get("missing_information"))
                    else f"Workflow intake is active and still needs: {'; '.join((workflow_action.output.get('missing_information') or [])[:4])}.",
                )
            )
        elif key == "summary":
            for action in execution_run.executed_actions:
                if action.status != "pending":
                    blocks.append(
                        AtomicContentBlock(
                            kind="summary",
                            payload={
                                "action_type": action.action_type,
                                "status": action.status,
                                "summary": action.summary,
                            },
                            text=f"{action.action_type}: {action.status}. {action.summary}".strip(),
                        )
                    )

    if not blocks:
        for action in execution_run.executed_actions:
            if action.status != "pending":
                blocks.append(
                    AtomicContentBlock(
                        kind="summary",
                        payload={"action_type": action.action_type, "status": action.status},
                        text=f"{action.action_type}: {action.status}.",
                    )
                )
    return blocks
