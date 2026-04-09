from __future__ import annotations

from typing import Any, Optional

from functools import lru_cache

from src.rag.service_page_ingestion import load_service_page_documents
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


def _normalize_identifier(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    return cleaned.upper()


def _first_value(values: list[str]) -> str:
    for value in values or []:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""


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
    explicit_service_turn = bool(parsed.entities.service_names and not parsed.entities.product_names)

    if deterministic_payload.catalog_numbers and not explicit_service_turn:
        confirmed_identifier_type = "catalog_number"
        reference_resolution = _normalize_identifier(deterministic_payload.catalog_numbers[0])
        reference_resolutions = [_normalize_identifier(value) for value in deterministic_payload.catalog_numbers]
    elif deterministic_payload.invoice_numbers:
        confirmed_identifier_type = "invoice_number"
        reference_resolution = _normalize_identifier(deterministic_payload.invoice_numbers[0])
        reference_resolutions = [_normalize_identifier(value) for value in deterministic_payload.invoice_numbers]
    elif deterministic_payload.order_numbers:
        confirmed_identifier_type = "order_number"
        reference_resolution = _normalize_identifier(deterministic_payload.order_numbers[0])
    elif reference_resolution_result.resolved_identifier and not (
        explicit_service_turn and reference_resolution_result.resolved_identifier_type == "catalog_number"
    ):
        confirmed_identifier_type = reference_resolution_result.resolved_identifier_type
        reference_resolution = _normalize_identifier(reference_resolution_result.resolved_identifier)
        reference_resolutions = [
            _normalize_identifier(value)
            for value in (reference_resolution_result.resolved_identifiers or [reference_resolution_result.resolved_identifier])
        ]
    elif turn_resolution.payload_usable and turn_resolution.resolved_identifier and not (
        explicit_service_turn and turn_resolution.resolved_identifier_type == "catalog_number"
    ):
        confirmed_identifier_type = turn_resolution.resolved_identifier_type
        reference_resolution = _normalize_identifier(turn_resolution.resolved_identifier)
        reference_resolutions = [_normalize_identifier(turn_resolution.resolved_identifier)]
    elif (
        session_payload.active_entity.identifier
        and turn_resolution.should_reuse_active_entity
        and not (explicit_service_turn and session_payload.active_entity.identifier_type == "catalog_number")
    ):
        reference_resolution = _normalize_identifier(session_payload.active_entity.identifier)
        confirmed_identifier_type = session_payload.active_entity.identifier_type
        reference_resolutions = [_normalize_identifier(session_payload.active_entity.identifier)]
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


def _normalize_lookup_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


@lru_cache(maxsize=1)
def _service_business_line_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for document in load_service_page_documents():
        metadata = dict(document.metadata)
        service_name = str(metadata.get("service_name") or "").strip()
        business_line = str(metadata.get("business_line") or "").strip()
        if not service_name or not business_line:
            continue
        mapping.setdefault(_normalize_lookup_text(service_name), business_line)
    return mapping


def _infer_business_line_from_service_name(parsed: ParsedResult) -> str:
    mapping = _service_business_line_map()
    for service_name in parsed.entities.service_names:
        business_line = mapping.get(_normalize_lookup_text(service_name))
        if business_line:
            return business_line
    return ""


def _build_current_entity(
    parsed: ParsedResult,
    interpreted_payload: InterpretedPayload,
    reference_resolution: ReferenceResolution,
    turn_resolution: TurnResolution,
    prior_payload: PersistedSessionPayload,
) -> ActiveEntityPayload:
    explicit_service_name = _first_value(list(parsed.entities.service_names))
    explicit_product_name = _first_value(list(parsed.entities.product_names))
    explicit_catalog_number = _normalize_identifier(_first_value(list(parsed.entities.catalog_numbers)))
    explicit_target = _first_value(list(parsed.entities.targets))

    business_line = (
        reference_resolution.resolved_business_line
        or turn_resolution.resolved_business_line
        or _infer_business_line_from_service_name(parsed)
        or prior_payload.active_business_line
        or prior_payload.active_entity.business_line
    )
    if explicit_service_name:
        return ActiveEntityPayload(
            identifier="",
            identifier_type="",
            entity_kind="service",
            display_name=explicit_service_name,
            business_line=business_line or "",
        )

    if explicit_product_name or explicit_catalog_number:
        return ActiveEntityPayload(
            identifier=explicit_catalog_number,
            identifier_type="catalog_number" if explicit_catalog_number else "",
            entity_kind="product",
            display_name=explicit_product_name or reference_resolution.resolved_display_name or prior_payload.active_entity.display_name or explicit_catalog_number,
            business_line=business_line or "",
        )

    if explicit_target:
        return ActiveEntityPayload(
            identifier="",
            identifier_type="",
            entity_kind="scientific_target",
            display_name=explicit_target,
            business_line=business_line or "",
        )

    identifier = _normalize_identifier(
        interpreted_payload.reference_resolution
        or reference_resolution.resolved_identifier
        or prior_payload.active_entity.identifier
    )
    identifier_type = (
        interpreted_payload.confirmed_identifier_type
        or reference_resolution.resolved_identifier_type
        or prior_payload.active_entity.identifier_type
    )
    display_name = (
        reference_resolution.resolved_display_name
        or prior_payload.active_entity.display_name
        or business_line.replace("_", "-")
    )

    entity_kind = prior_payload.active_entity.entity_kind
    if identifier_type == "catalog_number":
        entity_kind = "product"
    elif identifier_type in {"invoice_number", "order_number"}:
        entity_kind = "record"
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


def _resolve_active_context_fields(
    *,
    parsed: ParsedResult,
    current_entity: ActiveEntityPayload,
    prior_payload: PersistedSessionPayload,
    turn_resolution: TurnResolution,
) -> tuple[str, str, str]:
    explicit_service_name = _first_value(list(parsed.entities.service_names))
    explicit_product_name = _first_value(list(parsed.entities.product_names))
    explicit_target = _first_value(list(parsed.entities.targets))

    if turn_resolution.should_reset_route_context:
        return (
            explicit_service_name,
            explicit_product_name,
            explicit_target,
        )

    if explicit_service_name or current_entity.entity_kind == "service":
        return (
            explicit_service_name or current_entity.display_name,
            "",
            explicit_target or prior_payload.active_target or "",
        )

    if explicit_product_name or current_entity.entity_kind == "product":
        return (
            "",
            explicit_product_name or current_entity.display_name,
            explicit_target or prior_payload.active_target or "",
        )

    active_service_name = (
        (parsed.entities.service_names or [None])[0]
        or (current_entity.display_name if current_entity.entity_kind == "service" else None)
        or prior_payload.active_service_name
        or ""
    )
    active_product_name = (
        (parsed.entities.product_names or [None])[0]
        or (current_entity.display_name if current_entity.entity_kind == "product" else None)
        or prior_payload.active_product_name
        or ""
    )
    active_target = (
        (parsed.entities.targets or [None])[0]
        or prior_payload.active_target
        or ""
    )
    return active_service_name, active_product_name, active_target


def _resolve_revealed_attributes(
    *,
    current_entity: ActiveEntityPayload,
    prior_payload: PersistedSessionPayload,
    turn_resolution: TurnResolution,
) -> list[str]:
    if turn_resolution.should_reset_route_context:
        return []

    prior_entity = prior_payload.active_entity
    if not prior_entity.identifier and not prior_entity.display_name:
        return []

    if current_entity.entity_kind != prior_entity.entity_kind:
        return []

    if current_entity.entity_kind == "product":
        current_key = (current_entity.identifier or "").strip().lower() or (current_entity.display_name or "").strip().lower()
        prior_key = (prior_entity.identifier or "").strip().lower() or (prior_entity.display_name or "").strip().lower()
        if current_key and prior_key and current_key != prior_key:
            return []

    if current_entity.entity_kind == "service":
        if (current_entity.display_name or "").strip().lower() != (prior_entity.display_name or "").strip().lower():
            return []

    return list(prior_payload.revealed_attributes or [])


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
    active_service_name, active_product_name, active_target = _resolve_active_context_fields(
        parsed=parsed,
        current_entity=current_entity,
        prior_payload=prior_payload,
        turn_resolution=turn_resolution,
    )
    revealed_attributes = _resolve_revealed_attributes(
        current_entity=current_entity,
        prior_payload=prior_payload,
        turn_resolution=turn_resolution,
    )

    pending_identifier = ambiguous_identifiers[0] if ambiguous_identifiers else ""
    pending_question = _build_identifier_follow_up(ambiguous_identifiers)[0] if ambiguous_identifiers else ""

    return PersistedSessionPayload(
        active_entity=current_entity,
        recent_entities=recent_entities,
        active_service_name=active_service_name,
        active_product_name=active_product_name,
        active_target=active_target,
        pending_clarification=PendingClarificationPayload(
            field="identifier_type" if pending_identifier else "",
            candidate_identifier=pending_identifier,
            question=pending_question,
        ),
        active_business_line=current_entity.business_line or turn_resolution.resolved_business_line or prior_payload.active_business_line,
        last_user_goal=interpreted_payload.user_goal or prior_payload.last_user_goal,
        revealed_attributes=revealed_attributes,
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
