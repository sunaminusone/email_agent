from __future__ import annotations

from src.schemas import DeterministicPayload, InterpretedPayload, PersistedSessionPayload


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


def _query_already_mentions_reference(original_query: str, reference_resolution: str) -> bool:
    normalized_query = str(original_query or "").strip().lower()
    normalized_reference = str(reference_resolution or "").strip().lower()
    return bool(normalized_reference and normalized_reference in normalized_query)


def build_effective_query(
    original_query: str,
    interpreted_payload: InterpretedPayload,
    session_payload: PersistedSessionPayload,
) -> str:
    base_query = str(original_query or "").strip()
    active_entity = session_payload.active_entity
    active_identifier = active_entity.identifier if active_entity.entity_kind in {"product", "record"} else ""
    active_identifier_type = active_entity.identifier_type if active_entity.entity_kind in {"product", "record"} else ""
    reference = interpreted_payload.reference_resolution or active_identifier
    identifier_type = interpreted_payload.confirmed_identifier_type or active_identifier_type
    user_goal = interpreted_payload.user_goal or session_payload.last_user_goal

    if not reference:
        return base_query
    if _query_already_mentions_reference(base_query, reference):
        return base_query

    if identifier_type == "catalog_number":
        if user_goal == "request_documentation":
            return f"datasheet for {reference}"
        if user_goal == "request_pricing":
            return f"quote for {reference}"
        if user_goal == "request_timeline":
            return f"lead time for {reference}"
        return f"product {reference}"

    if identifier_type == "invoice_number":
        return f"invoice {reference}"

    if identifier_type == "order_number":
        return f"order {reference}"

    return base_query


def build_retrieval_query(
    original_query: str,
    deterministic_payload: DeterministicPayload,
    interpreted_payload: InterpretedPayload,
    effective_query: str,
) -> str:
    reference = interpreted_payload.reference_resolution
    identifier_type = interpreted_payload.confirmed_identifier_type
    document_types = deterministic_payload.document_types
    user_goal = interpreted_payload.user_goal

    if not reference:
        return effective_query or str(original_query or "").strip()

    if identifier_type == "catalog_number":
        if document_types:
            requested_documents = " and ".join(document_types)
            return f"{requested_documents} for catalog number {reference}"
        if user_goal == "request_pricing":
            return f"price and quote information for catalog number {reference}"
        if user_goal == "request_timeline":
            return f"lead time information for catalog number {reference}"
        return f"product information for catalog number {reference}"

    if identifier_type == "invoice_number":
        return f"invoice information for invoice number {reference}"

    if identifier_type == "order_number":
        return f"order information for order number {reference}"

    return effective_query or str(original_query or "").strip()
