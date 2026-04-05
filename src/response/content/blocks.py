from __future__ import annotations

from typing import Any

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
