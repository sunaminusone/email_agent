import re

from src.schemas import ParsedResult, RoutingMemory, TurnResolution


REFERENTIAL_FOLLOW_UP_MARKERS = (
    "also",
    "what about",
    "how about",
    "this one",
    "that one",
    "the product",
    "the service",
    "the brochure",
    "the flyer",
    "the booklet",
    "the datasheet",
    "same one",
    "same product",
    "same service",
    "it",
    "its",
    "it's",
)

EXPLICIT_NEW_REQUEST_PATTERNS = (
    "can you give me information about",
    "can you give me some information about",
    "give me information about",
    "share some information about",
    "information about",
    "tell me about",
    "what is ",
    "what are ",
    "i want information about",
    "do you have information about",
)

SHORT_CONFIRMATION_TERMS = {
    "yes",
    "yeah",
    "yep",
    "correct",
    "right",
    "exactly",
    "sure",
}

PRODUCT_CONFIRMATION_TERMS = (
    "it's a product",
    "it is a product",
    "its a product",
    "catalog number",
    "product number",
)

INVOICE_CONFIRMATION_TERMS = (
    "it's an invoice",
    "it is an invoice",
    "invoice",
    "billing record",
    "bill",
)

ORDER_CONFIRMATION_TERMS = (
    "it's an order",
    "it is an order",
    "purchase order",
    "order",
)

BUSINESS_LINE_PATTERNS = {
    "car_t": ("car-t", "car t", "car_t", "car-nk", "car nk", "car_nk"),
    "mrna_lnp": ("mrna-lnp", "mrna lnp", "mrna_lnp", "lnp"),
    "antibody": ("antibody", "antibodies", "monoclonal", "polyclonal", "humanization"),
    "other_service": ("baculovirus", "e.coli", "e coli", "yeast", "mammalian expression", "cell line"),
}


def _normalize_text(value: str) -> str:
    lowered = str(value or "").strip().lower()
    lowered = lowered.replace("_", " ").replace("-", " ")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def _detect_business_line(query: str) -> str:
    normalized = _normalize_text(query)
    for business_line, patterns in BUSINESS_LINE_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            return business_line
    return ""


def _looks_like_explicit_new_request(query: str) -> bool:
    normalized = _normalize_text(query)
    return any(pattern in normalized for pattern in EXPLICIT_NEW_REQUEST_PATTERNS)


def _looks_like_referential_follow_up(query: str) -> bool:
    normalized = _normalize_text(query)
    if len(normalized) <= 24:
        return True
    return any(marker in normalized for marker in REFERENTIAL_FOLLOW_UP_MARKERS)


def _looks_like_short_confirmation(query: str) -> bool:
    normalized = _normalize_text(query)
    return normalized in SHORT_CONFIRMATION_TERMS


def _resolve_identifier_type(query: str, routing_memory: RoutingMemory) -> str:
    normalized = _normalize_text(query)
    if any(term in normalized for term in PRODUCT_CONFIRMATION_TERMS):
        return "catalog_number"
    if any(term in normalized for term in INVOICE_CONFIRMATION_TERMS):
        return "invoice_number"
    if any(term in normalized for term in ORDER_CONFIRMATION_TERMS):
        return "order_number"
    if routing_memory.session_payload.active_entity.identifier_type:
        return routing_memory.session_payload.active_entity.identifier_type
    return ""


def _derive_user_goal(parsed: ParsedResult) -> str:
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
    return parsed.context.primary_intent or ""


def _has_current_payload(parsed: ParsedResult, query: str) -> bool:
    entities = parsed.entities
    return bool(
        entities.catalog_numbers
        or entities.order_numbers
        or entities.product_names
        or entities.service_names
        or entities.company_names
        or entities.targets
        or _detect_business_line(query)
    )


def resolve_turn(
    parsed: ParsedResult,
    original_query: str,
    routing_memory: RoutingMemory,
) -> TurnResolution:
    normalized_query = _normalize_text(original_query)
    active_entity = routing_memory.session_payload.active_entity
    pending = routing_memory.session_payload.pending_clarification
    current_business_line = _detect_business_line(original_query)
    active_business_line = routing_memory.active_business_line or routing_memory.session_payload.active_business_line
    explicit_new_request = _looks_like_explicit_new_request(original_query)
    referential_follow_up = _looks_like_referential_follow_up(original_query)
    current_has_payload = _has_current_payload(parsed, original_query)
    resolved_user_goal = _derive_user_goal(parsed) or routing_memory.session_payload.last_user_goal

    if parsed.request_flags.needs_documentation and not current_has_payload and not referential_follow_up:
        return TurnResolution(
            turn_type="fresh_request",
            confidence=0.82,
            should_reuse_active_route=False,
            should_resume_pending_route=False,
            should_reuse_active_entity=False,
            should_reuse_pending_identifier=False,
            should_reset_route_context=bool(routing_memory.active_route),
            payload_usable=False,
            payload_usable_fields=[],
            resolved_business_line=current_business_line,
            resolved_user_goal=resolved_user_goal,
            reason="The current turn is a generic documentation request without a product or business-line payload, so prior entity context should not be reused automatically.",
        )

    clarification_context = bool(pending.field or routing_memory.pending_route_after_clarification)
    if clarification_context and (
        _looks_like_short_confirmation(original_query)
        or any(term in normalized_query for term in PRODUCT_CONFIRMATION_TERMS + INVOICE_CONFIRMATION_TERMS + ORDER_CONFIRMATION_TERMS)
        or parsed.context.primary_intent == "follow_up"
    ):
        resolved_identifier = pending.candidate_identifier or active_entity.identifier
        resolved_identifier_type = _resolve_identifier_type(original_query, routing_memory)
        return TurnResolution(
            turn_type="clarification_answer",
            confidence=0.94 if resolved_identifier else 0.72,
            should_reuse_active_route=False,
            should_resume_pending_route=bool(routing_memory.pending_route_after_clarification),
            should_reuse_active_entity=bool(active_entity.identifier),
            should_reuse_pending_identifier=bool(resolved_identifier),
            should_reset_route_context=False,
            payload_usable=bool(resolved_identifier),
            payload_usable_fields=["pending_identifier", "active_entity"] if resolved_identifier else [],
            resolved_identifier=resolved_identifier,
            resolved_identifier_type=resolved_identifier_type,
            resolved_business_line=current_business_line or active_business_line,
            resolved_user_goal=resolved_user_goal or routing_memory.session_payload.last_user_goal,
            reason="The current turn looks like a clarification answer, so the pending identifier payload can be reused.",
        )

    if current_business_line and active_business_line and current_business_line != active_business_line:
        return TurnResolution(
            turn_type="new_request",
            confidence=0.92,
            should_reuse_active_route=False,
            should_resume_pending_route=False,
            should_reuse_active_entity=False,
            should_reuse_pending_identifier=False,
            should_reset_route_context=True,
            payload_usable=False,
            payload_usable_fields=[],
            resolved_business_line=current_business_line,
            resolved_user_goal=resolved_user_goal,
            reason="The current turn explicitly mentions a different business line, so prior route and payload context should be reset.",
        )

    if explicit_new_request and current_has_payload:
        return TurnResolution(
            turn_type="new_request",
            confidence=0.9,
            should_reuse_active_route=False,
            should_resume_pending_route=False,
            should_reuse_active_entity=False,
            should_reuse_pending_identifier=False,
            should_reset_route_context=bool(routing_memory.active_route),
            payload_usable=False,
            payload_usable_fields=[],
            resolved_business_line=current_business_line,
            resolved_user_goal=resolved_user_goal,
            reason="The current turn is phrased as a fresh information request with new scope, so previous route stickiness should not be applied.",
        )

    if (
        (parsed.context.primary_intent == "follow_up" or referential_follow_up)
        and active_entity.identifier
        and not explicit_new_request
    ):
        return TurnResolution(
            turn_type="follow_up",
            confidence=0.86,
            should_reuse_active_route=bool(routing_memory.active_route),
            should_resume_pending_route=False,
            should_reuse_active_entity=True,
            should_reuse_pending_identifier=False,
            should_reset_route_context=False,
            payload_usable=True,
            payload_usable_fields=["active_entity", "last_user_goal"],
            resolved_identifier=active_entity.identifier,
            resolved_identifier_type=active_entity.identifier_type,
            resolved_business_line=current_business_line or active_business_line,
            resolved_user_goal=resolved_user_goal or routing_memory.session_payload.last_user_goal,
            reason="The current turn looks like a referential follow-up, so the active entity payload can be reused.",
        )

    if routing_memory.active_route and not current_has_payload and not explicit_new_request:
        return TurnResolution(
            turn_type="route_continuation",
            confidence=0.62,
            should_reuse_active_route=True,
            should_resume_pending_route=False,
            should_reuse_active_entity=bool(active_entity.identifier),
            should_reuse_pending_identifier=False,
            should_reset_route_context=False,
            payload_usable=bool(active_entity.identifier or routing_memory.session_payload.last_user_goal),
            payload_usable_fields=["active_entity", "last_user_goal"] if (active_entity.identifier or routing_memory.session_payload.last_user_goal) else [],
            resolved_identifier=active_entity.identifier,
            resolved_identifier_type=active_entity.identifier_type,
            resolved_business_line=current_business_line or active_business_line,
            resolved_user_goal=resolved_user_goal or routing_memory.session_payload.last_user_goal,
            reason="The turn is short and does not introduce a new scoped request, so the active route may continue.",
        )

    return TurnResolution(
        turn_type="fresh_request",
        confidence=0.7 if current_has_payload else 0.45,
        should_reuse_active_route=False,
        should_resume_pending_route=False,
        should_reuse_active_entity=False,
        should_reuse_pending_identifier=False,
        should_reset_route_context=bool(routing_memory.active_route and current_has_payload),
        payload_usable=False,
        payload_usable_fields=[],
        resolved_business_line=current_business_line,
        resolved_user_goal=resolved_user_goal,
        reason="The turn should be handled as a fresh request and prior payload should not be reused by default.",
    )
