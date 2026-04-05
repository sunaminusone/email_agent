from __future__ import annotations

from typing import Any, Optional

from src.schemas import (
    ActiveEntityPayload,
    AttachmentSummary,
    ClarificationState,
    DeterministicPayload,
    InterpretedPayload,
    ParsedResult,
    PendingClarificationPayload,
    PersistedSessionPayload,
    ProductLookupKeys,
    ReferenceResolution,
    RoutingSignals,
    TurnResolution,
)
from src.strategies import detect_document_types


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


def _derive_user_goal(parsed: ParsedResult, original_query: str) -> str:
    flags = parsed.request_flags
    if flags.needs_documentation:
        return "request_documentation"
    if flags.needs_quote or flags.needs_price:
        return "request_pricing"
    if flags.needs_timeline:
        return "request_timeline"
    if flags.needs_invoice:
        return "request_invoice_information"
    if flags.needs_order_status:
        return "request_order_information"
    if parsed.context.primary_intent == "product_inquiry" or flags.needs_availability:
        return "request_product_information"

    normalized = str(original_query or "").strip().lower()
    if "product" in normalized or "catalog" in normalized:
        return "request_product_information"
    return parsed.context.primary_intent or ""


def build_deterministic_payload(parsed: ParsedResult, original_query: str) -> DeterministicPayload:
    document_types = detect_document_types(original_query)
    return DeterministicPayload(
        catalog_numbers=list(parsed.entities.catalog_numbers),
        invoice_numbers=list(parsed.entities.order_numbers) if parsed.request_flags.needs_invoice else [],
        order_numbers=list(parsed.entities.order_numbers),
        document_types=document_types,
        quantity=parsed.constraints.quantity,
        destination=parsed.constraints.destination,
    )


def build_interpreted_payload(
    parsed: ParsedResult,
    original_query: str,
    deterministic_payload: DeterministicPayload,
    routing_memory,
    turn_resolution: TurnResolution,
    reference_resolution_result: ReferenceResolution,
) -> InterpretedPayload:
    confirmed_identifier_type = ""
    reference_resolution = ""
    reference_resolutions: list[str] = []
    session_payload = routing_memory.session_payload

    if deterministic_payload.catalog_numbers:
        confirmed_identifier_type = "catalog_number"
        reference_resolution = deterministic_payload.catalog_numbers[0]
        reference_resolutions = list(deterministic_payload.catalog_numbers)
    elif deterministic_payload.invoice_numbers:
        confirmed_identifier_type = "invoice_number"
        reference_resolution = deterministic_payload.invoice_numbers[0]
        reference_resolutions = list(deterministic_payload.invoice_numbers)
    elif deterministic_payload.order_numbers:
        confirmed_identifier_type = "order_number"
        reference_resolution = deterministic_payload.order_numbers[0]
    elif reference_resolution_result.resolved_identifier:
        confirmed_identifier_type = reference_resolution_result.resolved_identifier_type
        reference_resolution = reference_resolution_result.resolved_identifier
        reference_resolutions = list(reference_resolution_result.resolved_identifiers or [reference_resolution_result.resolved_identifier])
    elif turn_resolution.payload_usable and turn_resolution.resolved_identifier:
        confirmed_identifier_type = turn_resolution.resolved_identifier_type
        reference_resolution = turn_resolution.resolved_identifier
        reference_resolutions = [turn_resolution.resolved_identifier]
    elif session_payload.active_entity.identifier and turn_resolution.should_reuse_active_entity:
        reference_resolution = session_payload.active_entity.identifier
        confirmed_identifier_type = session_payload.active_entity.identifier_type
        reference_resolutions = [session_payload.active_entity.identifier]
    else:
        reference_resolutions = []

    return InterpretedPayload(
        user_goal=turn_resolution.resolved_user_goal or _derive_user_goal(parsed, original_query),
        confirmed_identifier_type=confirmed_identifier_type,
        reference_resolution=reference_resolution,
        reference_resolutions=reference_resolutions,
    )


def _entity_has_signal(entity: ActiveEntityPayload) -> bool:
    return bool(entity.identifier or entity.display_name or entity.business_line)


def _build_current_entity(
    parsed: ParsedResult,
    interpreted_payload: InterpretedPayload,
    reference_resolution: ReferenceResolution,
    turn_resolution: TurnResolution,
    prior_payload: PersistedSessionPayload,
) -> ActiveEntityPayload:
    identifier = (
        interpreted_payload.reference_resolution
        or reference_resolution.resolved_identifier
        or prior_payload.active_entity.identifier
    )
    identifier_type = (
        interpreted_payload.confirmed_identifier_type
        or reference_resolution.resolved_identifier_type
        or prior_payload.active_entity.identifier_type
    )
    business_line = (
        reference_resolution.resolved_business_line
        or turn_resolution.resolved_business_line
        or prior_payload.active_business_line
        or prior_payload.active_entity.business_line
    )
    display_name = (
        (parsed.entities.product_names or [None])[0]
        or (parsed.entities.service_names or [None])[0]
        or reference_resolution.resolved_display_name
        or prior_payload.active_entity.display_name
        or business_line.replace("_", "-")
    )

    entity_kind = prior_payload.active_entity.entity_kind
    if identifier_type == "catalog_number":
        entity_kind = "product"
    elif identifier_type in {"invoice_number", "order_number"}:
        entity_kind = "record"
    elif parsed.entities.service_names:
        entity_kind = "service"
    elif business_line:
        entity_kind = "business_line"

    return ActiveEntityPayload(
        identifier=identifier,
        identifier_type=identifier_type,
        entity_kind=entity_kind,
        display_name=display_name or "",
        business_line=business_line or "",
    )


def _merge_recent_entities(
    prior_payload: PersistedSessionPayload,
    current_entity: ActiveEntityPayload,
    turn_resolution: TurnResolution,
    max_entities: int = 5,
) -> list[ActiveEntityPayload]:
    if turn_resolution.should_reset_route_context:
        return [current_entity] if _entity_has_signal(current_entity) else []

    ordered: list[ActiveEntityPayload] = []
    for entity in [current_entity, prior_payload.active_entity, *prior_payload.recent_entities]:
        if not _entity_has_signal(entity):
            continue
        signature = (
            entity.identifier.strip().lower(),
            entity.display_name.strip().lower(),
            entity.business_line.strip().lower(),
            entity.entity_kind.strip().lower(),
        )
        if signature in {
            (
                existing.identifier.strip().lower(),
                existing.display_name.strip().lower(),
                existing.business_line.strip().lower(),
                existing.entity_kind.strip().lower(),
            )
            for existing in ordered
        }:
            continue
        ordered.append(entity)

    return ordered[:max_entities]


def _build_identifier_follow_up(ambiguous_identifiers: list[str]) -> list[str]:
    if not ambiguous_identifiers:
        return []
    if len(ambiguous_identifiers) == 1:
        return [f"Please confirm whether {ambiguous_identifiers[0]} is a product/catalog number or an invoice/order number."]
    identifier_text = ", ".join(ambiguous_identifiers)
    return [f"Please confirm whether these identifiers refer to product/catalog numbers or invoice/order numbers: {identifier_text}."]


def build_session_payload(
    parsed: ParsedResult,
    deterministic_payload: DeterministicPayload,
    interpreted_payload: InterpretedPayload,
    reference_resolution: ReferenceResolution,
    ambiguous_identifiers: list[str],
    routing_memory,
    turn_resolution: TurnResolution,
) -> PersistedSessionPayload:
    prior_payload = routing_memory.session_payload
    current_entity = _build_current_entity(
        parsed,
        interpreted_payload,
        reference_resolution,
        turn_resolution,
        prior_payload,
    )
    recent_entities = _merge_recent_entities(prior_payload, current_entity, turn_resolution)

    pending_identifier = ambiguous_identifiers[0] if ambiguous_identifiers else ""
    pending_question = _build_identifier_follow_up(ambiguous_identifiers)[0] if ambiguous_identifiers else ""

    return PersistedSessionPayload(
        active_entity=current_entity,
        recent_entities=recent_entities,
        pending_clarification=PendingClarificationPayload(
            field="identifier_type" if pending_identifier else "",
            candidate_identifier=pending_identifier,
            question=pending_question,
        ),
        active_business_line=current_entity.business_line or turn_resolution.resolved_business_line or prior_payload.active_business_line,
        last_user_goal=interpreted_payload.user_goal or prior_payload.last_user_goal,
    )


def build_routing_signals(parsed: ParsedResult) -> RoutingSignals:
    context = parsed.context.model_dump()
    request_flags = parsed.request_flags.model_dump()

    return RoutingSignals(
        primary_intent=context["primary_intent"],
        secondary_intents=context["secondary_intents"],
        risk_level=context["risk_level"],
        urgency=context["urgency"],
        needs_human_review=context["needs_human_review"],
        has_missing_information=bool(parsed.missing_information),
        requires_clarification=bool(parsed.missing_information),
        is_pricing_request=request_flags["needs_price"] or request_flags["needs_quote"],
        is_technical_request=context["primary_intent"] in {"technical_question", "troubleshooting"},
        is_order_request=request_flags["needs_order_status"] or request_flags["needs_invoice"],
        is_shipping_request=request_flags["needs_shipping_info"],
        is_document_request=request_flags["needs_documentation"],
    )


def build_product_lookup_keys(
    parsed: ParsedResult,
    ambiguous_identifiers: Optional[list[str]] = None,
) -> ProductLookupKeys:
    entities = parsed.entities.model_dump()
    constraints = parsed.constraints.model_dump()
    request_flags = parsed.request_flags.model_dump()

    return ProductLookupKeys(
        product_names=entities["product_names"],
        catalog_numbers=entities["catalog_numbers"],
        ambiguous_identifiers=ambiguous_identifiers or [],
        service_names=entities["service_names"],
        targets=entities["targets"],
        species=entities["species"],
        applications=entities["applications"],
        quantity=constraints["quantity"],
        destination=constraints["destination"],
        preferred_supplier_or_brand=constraints["preferred_supplier_or_brand"],
        grade_or_quality=constraints["grade_or_quality"],
        format_or_size=constraints["format_or_size"],
        needs_quote=request_flags["needs_quote"],
        needs_price=request_flags["needs_price"],
        needs_availability=request_flags["needs_availability"],
        needs_timeline=request_flags["needs_timeline"],
    )


def build_clarification_state(parsed: ParsedResult) -> ClarificationState:
    missing_information = parsed.missing_information
    return ClarificationState(
        requires_clarification=bool(missing_information),
        missing_information=missing_information,
        blocking_missing_fields=missing_information,
        optional_missing_fields=[],
    )


def build_attachment_summary(attachments: list[dict[str, Any]]) -> AttachmentSummary:
    file_names = [attachment.get("file_name") for attachment in attachments if attachment.get("file_name")]
    file_types = [attachment.get("file_type") for attachment in attachments if attachment.get("file_type")]

    return AttachmentSummary(
        attachment_count=len(attachments),
        has_attachments=bool(attachments),
        file_names=file_names,
        file_types=file_types,
    )
