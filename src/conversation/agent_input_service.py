from __future__ import annotations

from typing import Any, Optional

from src.conversation.payload_builders import (
    build_attachment_summary,
    build_clarification_state,
    build_deterministic_payload,
    build_interpreted_payload,
    build_product_lookup_keys,
    build_routing_signals,
    build_session_payload,
)
from src.conversation.payload_merge_service import (
    apply_reference_resolution,
    apply_turn_resolution,
    enrich_parsed_result_with_identifier_fallback,
    merge_routing_memory_with_turn_resolution,
)
from src.conversation.query_resolution import (
    build_effective_query,
    build_retrieval_query,
)
from src.conversation.reference_resolution_service import resolve_reference
from src.conversation.routing_state_service import build_routing_memory
from src.conversation.turn_resolution_service import resolve_turn
from src.schemas import AgentContext, RoutingDebugInfo
from src.parser.service import parse_user_input


def build_agent_input(
    thread_id: Optional[str],
    original_query: str,
    parsed,
    conversation_history: Optional[list[dict[str, str]]] = None,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> AgentContext:
    conversation_history = conversation_history or []
    attachments = attachments or []

    enrichment = enrich_parsed_result_with_identifier_fallback(parsed, original_query)
    parsed = enrichment["parsed"]
    fallback_ambiguous_identifiers = enrichment["ambiguous_identifiers"]

    routing_memory = build_routing_memory(parsed, conversation_history, original_query)
    turn_resolution = resolve_turn(parsed, original_query, routing_memory)
    reference_resolution = resolve_reference(original_query, turn_resolution, routing_memory.session_payload)
    routing_memory = merge_routing_memory_with_turn_resolution(routing_memory, turn_resolution)
    parsed = apply_turn_resolution(parsed, turn_resolution)
    parsed = apply_reference_resolution(parsed, reference_resolution)

    normalized_query = parsed.normalized_query or original_query.strip()
    routing_signals = build_routing_signals(parsed)
    active_ambiguous_identifiers = [] if turn_resolution.should_reuse_pending_identifier else fallback_ambiguous_identifiers

    deterministic_payload = build_deterministic_payload(parsed, original_query)
    interpreted_payload = build_interpreted_payload(
        parsed,
        original_query,
        deterministic_payload,
        routing_memory,
        turn_resolution,
        reference_resolution,
    )
    session_payload = build_session_payload(
        parsed,
        deterministic_payload,
        interpreted_payload,
        reference_resolution,
        active_ambiguous_identifiers,
        routing_memory,
        turn_resolution,
    )
    effective_query = build_effective_query(original_query, interpreted_payload, session_payload)
    retrieval_query = build_retrieval_query(original_query, deterministic_payload, interpreted_payload, effective_query)
    product_lookup_keys = build_product_lookup_keys(parsed, active_ambiguous_identifiers)
    clarification_state = build_clarification_state(parsed)
    attachment_summary = build_attachment_summary(attachments)

    return AgentContext(
        thread_id=thread_id,
        query=normalized_query,
        original_query=original_query,
        original_email_text=original_query,
        normalized_query=normalized_query,
        effective_query=effective_query,
        retrieval_query=retrieval_query,
        context=parsed.context,
        entities=parsed.entities,
        request_flags=parsed.request_flags,
        constraints=parsed.constraints,
        open_slots=parsed.open_slots,
        retrieval_hints=parsed.retrieval_hints,
        tool_hints=parsed.tool_hints,
        missing_information=parsed.missing_information,
        routing_signals=routing_signals,
        routing_debug=RoutingDebugInfo(),
        deterministic_payload=deterministic_payload,
        interpreted_payload=interpreted_payload,
        reference_resolution=reference_resolution,
        session_payload=session_payload,
        turn_resolution=turn_resolution,
        product_lookup_keys=product_lookup_keys,
        clarification_state=clarification_state,
        routing_memory=routing_memory,
        attachment_summary=attachment_summary,
        conversation_history=conversation_history,
        attachments=attachments,
        extra_instructions=parsed.extra_instructions,
    )


def make_agent_input(
    user_query: str,
    thread_id: Optional[str] = None,
    conversation_history: Optional[list[dict[str, str]]] = None,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> AgentContext:
    parsed = parse_user_input(
        user_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
    )

    return build_agent_input(
        thread_id=thread_id,
        original_query=user_query,
        parsed=parsed,
        conversation_history=conversation_history,
        attachments=attachments,
    )
