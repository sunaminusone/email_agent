from __future__ import annotations

import re
from typing import Any, Mapping


SERVICE_SCOPE_QUERY_PATTERNS = (
    re.compile(r"\bmodel(?:s)?\b"),
    re.compile(r"\bsupport(?:ed)?\b"),
    re.compile(r"\bworkflow(?:s)?\b"),
    re.compile(r"\btimeline(?:s)?\b"),
    re.compile(r"\bplan(?:s)?\b"),
    re.compile(r"\bphase(?:s)?\b"),
    re.compile(r"\bvalidate(?:s|d|ion)?\b"),
    re.compile(r"\bapplication(?:s)?\b"),
    re.compile(r"\buse case(?:s)?\b"),
)

NON_TECHNICAL_FALLBACK_PATTERNS = (
    re.compile(r"\bprice(?:s|d|ing)?\b"),
    re.compile(r"\bquote(?:s|d)?\b"),
    re.compile(r"\bcost(?:s)?\b"),
    re.compile(r"\binvoice(?:s)?\b"),
    re.compile(r"\border(?:s|ed|ing)?\b"),
    re.compile(r"\bshipping\b"),
    re.compile(r"\bdelivery\b"),
    re.compile(r"\btracking\b"),
    re.compile(r"\beta\b"),
    re.compile(r"\bbrochure(?:s)?\b"),
    re.compile(r"\bdatasheet(?:s)?\b"),
    re.compile(r"\bflyer(?:s)?\b"),
    re.compile(r"\bmanual(?:s)?\b"),
    re.compile(r"\bprotocol(?:s)?\b"),
    re.compile(r"\bcoa\b"),
    re.compile(r"\bsds\b"),
    re.compile(r"\bdocument(?:s|ation)?\b"),
    re.compile(r"\bcontact\b"),
    re.compile(r"\brepresentative\b"),
    re.compile(r"\bsales rep\b"),
    re.compile(r"\bcustomer support\b"),
    re.compile(r"\btechnical support\b"),
    re.compile(r"\bsupport team\b"),
    re.compile(r"\bconnect me\b"),
    re.compile(r"\bput me in touch\b"),
    re.compile(r"\breach out\b"),
)

PRODUCT_SCOPE_QUERY_PATTERNS = (
    re.compile(r"\bapplication(?:s)?\b"),
    re.compile(r"\bvalidate(?:s|d|ion)?\b"),
    re.compile(r"\bspecies\b"),
    re.compile(r"\breactivit(?:y|ies)\b"),
    re.compile(r"\bhost\b"),
    re.compile(r"\bclonality\b"),
    re.compile(r"\bclone\b"),
    re.compile(r"\bstorage\b"),
    re.compile(r"\bbuffer\b"),
    re.compile(r"\bformulation\b"),
    re.compile(r"\bpurity\b"),
    re.compile(r"\bconcentration\b"),
)


def normalize_scope_query(value: str) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def query_has_service_scope_marker(query: str) -> bool:
    normalized_query = normalize_scope_query(query)
    if not normalized_query:
        return False
    return any(pattern.search(normalized_query) for pattern in SERVICE_SCOPE_QUERY_PATTERNS)


def query_matches_non_technical_fallback_path(query: str) -> bool:
    normalized_query = normalize_scope_query(query)
    if not normalized_query:
        return False
    return any(pattern.search(normalized_query) for pattern in NON_TECHNICAL_FALLBACK_PATTERNS)


def query_has_product_scope_marker(query: str) -> bool:
    normalized_query = normalize_scope_query(query)
    if not normalized_query:
        return False
    return any(pattern.search(normalized_query) for pattern in PRODUCT_SCOPE_QUERY_PATTERNS)


def is_service_scoped_follow_up(query: str, active_service_name: str) -> bool:
    return bool(str(active_service_name or "").strip()) and query_has_service_scope_marker(query)


def _first_value(values: Any) -> str:
    if isinstance(values, list):
        for value in values:
            cleaned = str(value or "").strip()
            if cleaned:
                return cleaned
        return ""
    return str(values or "").strip()


def _query(agent_input: Mapping[str, Any]) -> str:
    return str(
        agent_input.get("original_query")
        or agent_input.get("effective_query")
        or agent_input.get("query")
        or ""
    )


def _entities(agent_input: Mapping[str, Any]) -> Mapping[str, Any]:
    entities = agent_input.get("entities", {})
    return entities if isinstance(entities, Mapping) else {}


def _product_lookup_keys(agent_input: Mapping[str, Any]) -> Mapping[str, Any]:
    product_lookup_keys = agent_input.get("product_lookup_keys", {})
    return product_lookup_keys if isinstance(product_lookup_keys, Mapping) else {}


def _session_payload(agent_input: Mapping[str, Any]) -> Mapping[str, Any]:
    session_payload = agent_input.get("session_payload", {})
    if isinstance(session_payload, Mapping) and session_payload:
        return session_payload

    memory_snapshot = agent_input.get("memory_snapshot", {})
    if isinstance(memory_snapshot, Mapping):
        object_memory = memory_snapshot.get("object_memory", {})
        if not isinstance(object_memory, Mapping):
            object_memory = {}
        active_object = object_memory.get("active_object", {})
        if not isinstance(active_object, Mapping):
            active_object = {}
        clarification_memory = memory_snapshot.get("clarification_memory", {})
        if not isinstance(clarification_memory, Mapping):
            clarification_memory = {}
        thread_memory = memory_snapshot.get("thread_memory", {})
        if not isinstance(thread_memory, Mapping):
            thread_memory = {}

        active_display_name = active_object.get("display_name", "")
        active_object_type = active_object.get("object_type", "")
        return {
            "active_entity": {
                "identifier": active_object.get("identifier", ""),
                "identifier_type": active_object.get("identifier_type", ""),
                "entity_kind": active_object_type,
                "display_name": active_display_name,
                "business_line": active_object.get("business_line", ""),
            },
            "active_service_name": active_display_name if active_object_type == "service" else "",
            "active_product_name": active_display_name if active_object_type == "product" else "",
            "active_target": active_display_name if active_object_type == "scientific_target" else "",
            "pending_clarification": {
                "field": clarification_memory.get("pending_clarification_type", ""),
                "candidate_options": clarification_memory.get("pending_candidate_options", []),
                "candidate_identifier": clarification_memory.get("pending_identifier", ""),
                "question": clarification_memory.get("pending_question", ""),
            },
            "active_business_line": thread_memory.get("active_business_line", ""),
            "last_user_goal": thread_memory.get("last_user_goal", ""),
        }

    route_state = agent_input.get("route_state", {})
    if not isinstance(route_state, Mapping):
        return {}

    object_memory = route_state.get("object_memory", {})
    if not isinstance(object_memory, Mapping):
        object_memory = {}
    active_object = object_memory.get("active_object", {})
    if not isinstance(active_object, Mapping):
        active_object = {}

    return {
        "active_entity": {
            "identifier": active_object.get("identifier", ""),
            "identifier_type": active_object.get("identifier_type", ""),
            "entity_kind": active_object.get("object_type", ""),
            "display_name": active_object.get("display_name", ""),
            "business_line": active_object.get("business_line", ""),
        },
        "active_service_name": "",
        "active_product_name": active_object.get("display_name", ""),
        "active_target": "",
    }


def _routing_memory(agent_input: Mapping[str, Any]) -> Mapping[str, Any]:
    routing_memory = agent_input.get("routing_memory", {})
    return routing_memory if isinstance(routing_memory, Mapping) else {}


def _active_entity(agent_input: Mapping[str, Any]) -> Mapping[str, Any]:
    active_entity = _session_payload(agent_input).get("active_entity", {})
    return active_entity if isinstance(active_entity, Mapping) else {}


def _prior_active_entity(agent_input: Mapping[str, Any]) -> Mapping[str, Any]:
    routing_memory = _routing_memory(agent_input)
    memory_snapshot = routing_memory.get("memory_snapshot", {}) if isinstance(routing_memory, Mapping) else {}
    if isinstance(memory_snapshot, Mapping):
        object_memory = memory_snapshot.get("object_memory", {})
        active_object = object_memory.get("active_object", {}) if isinstance(object_memory, Mapping) else {}
        if isinstance(active_object, Mapping):
            return {
                "identifier": active_object.get("identifier", ""),
                "identifier_type": active_object.get("identifier_type", ""),
                "entity_kind": active_object.get("object_type", ""),
                "display_name": active_object.get("display_name", ""),
                "business_line": active_object.get("business_line", ""),
            }

    session_payload = routing_memory.get("session_payload", {}) if isinstance(routing_memory, Mapping) else {}
    active_entity = session_payload.get("active_entity", {}) if isinstance(session_payload, Mapping) else {}
    return active_entity if isinstance(active_entity, Mapping) else {}


def _turn_type(agent_input: Mapping[str, Any]) -> str:
    turn_resolution = agent_input.get("turn_resolution", {})
    if not isinstance(turn_resolution, Mapping):
        return ""
    return str(turn_resolution.get("turn_type") or "").strip()


def _primary_intent(agent_input: Mapping[str, Any]) -> str:
    context = agent_input.get("context", {})
    if not isinstance(context, Mapping):
        return ""
    return str(context.get("primary_intent") or "").strip()


def _is_continuation_turn(agent_input: Mapping[str, Any]) -> bool:
    if _turn_type(agent_input) in {"follow_up", "route_continuation"}:
        return True
    if _primary_intent(agent_input) == "follow_up":
        return True
    return bool(_routing_memory(agent_input).get("should_stick_to_active_route"))


def _resolved_scope(scope_type: str, source: str, name: str, reason: str) -> dict[str, str]:
    return {
        "scope_type": scope_type,
        "source": source,
        "name": str(name or "").strip(),
        "reason": reason,
    }


def _no_scope(reason: str) -> dict[str, str]:
    return _resolved_scope("", "", "", reason)


def resolve_current_scope(agent_input: Mapping[str, Any]) -> dict[str, str]:
    entities = _entities(agent_input)
    product_lookup_keys = _product_lookup_keys(agent_input)

    service_name = _first_value(entities.get("service_names") or product_lookup_keys.get("service_names"))
    if service_name:
        return _resolved_scope("service", "current", service_name, "current_service_scope")

    product_name = _first_value(entities.get("product_names") or product_lookup_keys.get("product_names"))
    catalog_number = _first_value(entities.get("catalog_numbers") or product_lookup_keys.get("catalog_numbers"))
    if product_name or catalog_number:
        return _resolved_scope("product", "current", product_name or catalog_number, "current_product_scope")

    target_name = _first_value(entities.get("targets") or product_lookup_keys.get("targets"))
    if target_name:
        return _resolved_scope("scientific_target", "current", target_name, "current_scientific_target_scope")

    return _no_scope("no_current_scope")


def has_current_scope(agent_input: Mapping[str, Any]) -> bool:
    return bool(resolve_current_scope(agent_input)["scope_type"])


def resolve_active_scope(agent_input: Mapping[str, Any]) -> dict[str, str]:
    current_scope = resolve_current_scope(agent_input)
    if current_scope["scope_type"]:
        return _no_scope(f"blocked_by_{current_scope['reason']}")

    if not _is_continuation_turn(agent_input):
        return _no_scope("blocked_by_non_continuation_turn")

    query = _query(agent_input)
    if query_matches_non_technical_fallback_path(query):
        return _no_scope("blocked_by_non_technical_path")

    session_payload = _session_payload(agent_input)
    active_entity = _active_entity(agent_input)
    prior_active_entity = _prior_active_entity(agent_input)
    current_active_entity_kind = str(active_entity.get("entity_kind") or "").strip()
    prior_active_entity_kind = str(prior_active_entity.get("entity_kind") or "").strip()
    active_service_name = str(
        agent_input.get("active_service_name")
        or session_payload.get("active_service_name")
        or ""
    ).strip()
    active_product_name = str(
        agent_input.get("active_product_name")
        or session_payload.get("active_product_name")
        or ""
    ).strip()
    active_target = str(
        agent_input.get("active_target")
        or session_payload.get("active_target")
        or ""
    ).strip()

    if current_active_entity_kind in {"service", "product", "scientific_target"}:
        active_entity_kind = current_active_entity_kind
    elif prior_active_entity_kind in {"service", "product", "scientific_target"}:
        active_entity_kind = prior_active_entity_kind
    elif active_service_name:
        active_entity_kind = "service"
    elif active_product_name:
        active_entity_kind = "product"
    elif active_target:
        active_entity_kind = "scientific_target"
    else:
        active_entity_kind = current_active_entity_kind or prior_active_entity_kind

    if active_entity_kind == "service" and is_service_scoped_follow_up(query, active_service_name):
        return _resolved_scope(
            "service",
            "active",
            active_service_name,
            "active_service_follow_up_matched_service_scope_markers",
        )

    if active_entity_kind == "product" and active_product_name and query_has_product_scope_marker(query):
        return _resolved_scope(
            "product",
            "active",
            active_product_name,
            "active_product_follow_up_matched_product_scope_markers",
        )

    if active_target and query_has_product_scope_marker(query):
        return _resolved_scope(
            "scientific_target",
            "active",
            active_target,
            "active_target_follow_up_matched_product_scope_markers",
        )

    return _no_scope("no_active_scope")


def resolve_effective_scope(agent_input: Mapping[str, Any]) -> dict[str, str]:
    current_scope = resolve_current_scope(agent_input)
    if current_scope["scope_type"]:
        return current_scope
    return resolve_active_scope(agent_input)


def should_fallback_to_active_service_context(
    *,
    query: str,
    active_service_name: str,
    active_entity_kind: str,
    turn_type: str,
    has_current_scope: bool,
) -> bool:
    resolved_scope = resolve_active_scope(
        {
            "query": query,
            "active_service_name": active_service_name,
            "session_payload": {
                "active_entity": {
                    "entity_kind": active_entity_kind,
                }
            },
            "turn_resolution": {
                "turn_type": turn_type,
            },
            "entities": {
                "service_names": [],
                "product_names": [],
                "catalog_numbers": [],
                "targets": [],
            },
            "product_lookup_keys": {
                "service_names": [],
                "product_names": [],
                "catalog_numbers": [],
                "targets": [],
            },
        }
        if not has_current_scope
        else {
            "query": query,
            "entities": {
                "targets": ["current_scope_present"],
            },
            "session_payload": {
                "active_entity": {
                    "entity_kind": active_entity_kind,
                }
            },
            "active_service_name": active_service_name,
            "turn_resolution": {
                "turn_type": turn_type,
            },
        }
    )
    return resolved_scope["scope_type"] == "service" and resolved_scope["source"] == "active"


__all__ = [
    "NON_TECHNICAL_FALLBACK_PATTERNS",
    "PRODUCT_SCOPE_QUERY_PATTERNS",
    "SERVICE_SCOPE_QUERY_PATTERNS",
    "has_current_scope",
    "is_service_scoped_follow_up",
    "normalize_scope_query",
    "query_has_product_scope_marker",
    "query_matches_non_technical_fallback_path",
    "query_has_service_scope_marker",
    "resolve_active_scope",
    "resolve_current_scope",
    "resolve_effective_scope",
    "should_fallback_to_active_service_context",
]
