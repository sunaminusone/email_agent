from typing import Any, Dict, List

from src.schemas import ParsedResult, PersistedSessionPayload, RoutingMemory


def _extract_route_state_from_metadata(conversation_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    for message in reversed(conversation_history):
        metadata = message.get("metadata", {}) or {}
        route_state = metadata.get("route_state")
        if isinstance(route_state, dict):
            return route_state
    return {}


def _looks_like_clarification_prompt(text: str) -> bool:
    lowered = text.lower()
    patterns = [
        "could you share",
        "please provide",
        "please confirm",
        "need the following information",
        "补充",
        "请提供",
        "请确认",
        "还需要这些信息",
    ]
    return any(pattern in lowered for pattern in patterns)


def _looks_like_follow_up_payload(text: str) -> bool:
    lowered = text.lower().strip()
    if len(lowered) <= 80:
        return True
    payload_markers = [
        "catalog",
        "pm-",
        "order",
        "destination",
        "quantity",
        "california",
        "货号",
        "数量",
        "发往",
        "目的地",
        "订单号",
    ]
    return any(marker in lowered for marker in payload_markers)


def _looks_like_explicit_new_request(text: str) -> bool:
    lowered = text.lower().strip()
    fresh_request_patterns = [
        "can you give me information about",
        "can you give me some information about",
        "tell me about",
        "information about",
        "what is ",
        "what are ",
        "share some information about",
        "i want information about",
        "do you have information about",
    ]
    return any(pattern in lowered for pattern in fresh_request_patterns)


def build_routing_memory(
    parsed: ParsedResult,
    conversation_history: List[Dict[str, Any]],
    original_query: str,
) -> RoutingMemory:
    route_state = _extract_route_state_from_metadata(conversation_history)
    last_assistant = next((msg for msg in reversed(conversation_history) if msg.get("role") == "assistant"), {})
    current_query = original_query.strip()

    active_route = route_state.get("active_route")
    pending_route = route_state.get("pending_route_after_clarification")
    active_secondary_routes = route_state.get("active_secondary_routes", [])
    active_business_line = route_state.get("active_business_line", "")
    active_engagement_type = route_state.get("active_engagement_type", "")
    carried_missing_information = route_state.get("carried_missing_information", [])
    pending_identifiers = route_state.get("pending_identifiers", [])
    session_payload = PersistedSessionPayload.model_validate(route_state.get("session_payload", {}) or {})
    last_prompt_type = route_state.get("last_assistant_prompt_type", "")

    route_phase = route_state.get("route_phase", "unknown")
    continuity_mode = "fresh_request"
    continuity_confidence = 0.2
    should_stick_to_active_route = False
    should_resume_pending_route = False
    state_reason = "No active route state was found in conversation history."

    if active_route:
        continuity_mode = "route_continuation"
        continuity_confidence = 0.8
        should_stick_to_active_route = not _looks_like_explicit_new_request(current_query)
        route_phase = route_phase if route_phase != "unknown" else "active"
        state_reason = "Recovered active route state from conversation history metadata."

    if pending_route and route_phase == "waiting_for_user":
        continuity_mode = "clarification_reply"
        continuity_confidence = 0.9
        should_stick_to_active_route = False
        should_resume_pending_route = not bool(parsed.missing_information)
        route_phase = "ready_to_resume" if should_resume_pending_route else "waiting_for_user"
        state_reason = "Recovered a pending post-clarification route from conversation history metadata."

    if not active_route and last_assistant.get("content") and _looks_like_clarification_prompt(last_assistant["content"]):
        continuity_mode = "clarification_reply"
        continuity_confidence = 0.55
        route_phase = "waiting_for_user"
        should_resume_pending_route = _looks_like_follow_up_payload(current_query) and not bool(parsed.missing_information)
        state_reason = "Inferred a clarification follow-up from the last assistant message."

    if parsed.context.primary_intent == "follow_up":
        continuity_mode = "follow_up"
        continuity_confidence = max(continuity_confidence, 0.7)
        should_stick_to_active_route = bool(active_route)
        state_reason = "Parser marked the current user message as a follow-up."

    if _looks_like_explicit_new_request(current_query):
        should_stick_to_active_route = False
        should_resume_pending_route = False
        if active_route:
            continuity_mode = "fresh_request"
            continuity_confidence = 0.35
            state_reason = "Detected an explicit new information request, so prior route stickiness was relaxed."

    memory = RoutingMemory(
        active_route=active_route,
        pending_route_after_clarification=pending_route,
        active_secondary_routes=active_secondary_routes,
        route_phase=route_phase,
        continuity_mode=continuity_mode,
        continuity_confidence=continuity_confidence,
        should_stick_to_active_route=should_stick_to_active_route,
        should_resume_pending_route=should_resume_pending_route,
        last_assistant_prompt_type=last_prompt_type or ("clarification_request" if continuity_mode == "clarification_reply" else ""),
        active_business_line=active_business_line,
        active_engagement_type=active_engagement_type,
        carried_missing_information=carried_missing_information or parsed.missing_information,
        pending_identifiers=(
            pending_identifiers
            or list(session_payload.pending_clarification.candidate_options)
            or ([session_payload.pending_clarification.candidate_identifier] if session_payload.pending_clarification.candidate_identifier else [])
        ),
        session_payload=session_payload,
        state_reason=state_reason,
    )
    return memory
