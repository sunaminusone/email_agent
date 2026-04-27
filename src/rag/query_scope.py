from __future__ import annotations

import re
import warnings
from typing import Any, Mapping

from src.objects.registries.service_registry import (
    canonicalize_service_name as _canonicalize_via_registry,
)


def canonicalize_service_name(value: str) -> str:
    # Route caller-supplied service names through service_registry's alias
    # table so aliases resolve to the canonical name that chunk metadata
    # carries — retriever's active_service_boost relies on string equality
    # with _service_label(metadata). Idempotent on canonical input; passes
    # through unchanged when no alias matches or the alias is ambiguous.
    return _canonicalize_via_registry(value)


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


def query_mentions_scope(query: str, scope_name: str) -> bool:
    normalized_query = normalize_scope_query(query)
    normalized_scope = normalize_scope_query(scope_name)
    return bool(normalized_scope and normalized_scope in normalized_query)


# Full 1:1 projection from parser semantic_intent to retrieval bucket. Every
# value in SEMANTIC_INTENT_VALUES must appear here — adding a new canonical
# intent without updating this table triggers the warning path below.
#
# Notes:
#   - `troubleshooting` → general_technical is pragmatic: KB currently has no
#     troubleshooting_guide / faq section_type. If KB adds troubleshooting
#     content, split troubleshooting into its own bucket with section boosts.
#   - `follow_up` → follow_up is a placeholder bucket. Semantically follow_up
#     is a dialogue_act concept; the "right" bucket is whatever the prior turn
#     was asking about. Until routing carries that forward, follow_up stays a
#     telemetry-only bucket (empty section boost).
_SEMANTIC_INTENT_BUCKET_MAP: dict[str, str] = {
    "pricing_question": "pricing",
    "timeline_question": "timeline",
    "workflow_question": "workflow",
    "model_support_question": "model_support",
    "service_plan_question": "service_plan",
    "documentation_request": "documentation",
    "customization_request": "customization",
    "technical_question": "general_technical",
    "troubleshooting": "general_technical",
    "product_inquiry": "general_technical",
    "shipping_question": "operational",
    "order_support": "operational",
    "complaint": "operational",
    "general_info": "general_info",
    "follow_up": "follow_up",
    "unknown": "unknown",
}


def detect_intent_bucket(query: str, semantic_intent: str = "") -> str:
    # Parser-assigned semantic_intent is authoritative: 1:1 projection to the
    # retrieval bucket. Keyword fallback only runs when parser did not produce
    # an intent at all (legacy callers, empty string).
    cleaned_intent = str(semantic_intent or "").strip()

    if cleaned_intent:
        mapped = _SEMANTIC_INTENT_BUCKET_MAP.get(cleaned_intent)
        if mapped:
            return mapped
        # Non-empty intent that isn't in the map means parser emitted a value
        # outside SEMANTIC_INTENT_VALUES — real drift, not a benign case.
        warnings.warn(
            f"detect_intent_bucket: unmapped semantic_intent {cleaned_intent!r}; "
            "falling back to general_technical. Update _SEMANTIC_INTENT_BUCKET_MAP.",
            stacklevel=2,
        )
        return "general_technical"

    normalized_query = normalize_scope_query(query)
    if not normalized_query:
        return "general_technical"

    if any(term in normalized_query for term in ("service plan", "plan", "timeline", "phase", "stages")):
        return "service_plan"
    if any(term in normalized_query for term in ("workflow", "next step", "happens next", "what happens next", "process", "after")):
        return "workflow"
    if any(term in normalized_query for term in ("model", "models", "cell types")):
        return "model_support"

    return "general_technical"


# Bucket modes separate three orthogonal concerns:
#   - ranked: uses section_type boosts (must have an entry in _SECTION_TYPE_BOOSTS)
#   - lexical_only: participates in RAG via keyword injection / query rewrite,
#     no section boosts (either no section_type target in KB, or "no preference"
#     by design — e.g. general_technical is the catch-all parent bucket)
#   - non_rag: bucket's intents shouldn't drive technical RAG at all; reaching
#     RAG with this mode emits a telemetry warning (weak enforcement for now —
#     strong short-circuit is a separate PR once all callers are audited)
#   - placeholder: runtime-equivalent to lexical_only, but flags "temporary,
#     awaiting upgrade" vs. "by design" (e.g. follow_up needs prior-turn intent
#     carry — see backlog #8; unknown is an admit-you-don't-know terminal)
#
# Invariants enforced by tests:
#   - every bucket in _SEMANTIC_INTENT_BUCKET_MAP.values() must have a mode
#   - ranked ↔ presence in _SECTION_TYPE_BOOSTS
_BUCKET_MODES: dict[str, str] = {
    "pricing": "ranked",
    "timeline": "ranked",
    "workflow": "ranked",
    "model_support": "ranked",
    "service_plan": "ranked",
    "general_technical": "lexical_only",
    "documentation": "lexical_only",
    "customization": "lexical_only",
    "operational": "non_rag",
    "general_info": "lexical_only",
    "follow_up": "placeholder",
    "unknown": "placeholder",
}


def get_bucket_mode(bucket: str) -> str:
    return _BUCKET_MODES.get(str(bucket or "").strip(), "")


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


def _semantic_intent(agent_input: Mapping[str, Any]) -> str:
    context = agent_input.get("context", {})
    if not isinstance(context, Mapping):
        return ""
    return str(context.get("semantic_intent") or "").strip()


def _is_continuation_turn(agent_input: Mapping[str, Any]) -> bool:
    if _turn_type(agent_input) in {"follow_up", "route_continuation"}:
        return True
    if _semantic_intent(agent_input) == "follow_up":
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

    return _no_scope("no_current_scope")


def has_current_scope(agent_input: Mapping[str, Any]) -> bool:
    return bool(resolve_current_scope(agent_input)["scope_type"])


def resolve_active_scope(agent_input: Mapping[str, Any]) -> dict[str, str]:
    current_scope = resolve_current_scope(agent_input)
    if current_scope["scope_type"]:
        return _no_scope(f"blocked_by_{current_scope['reason']}")

    query = _query(agent_input)
    if query_matches_non_technical_fallback_path(query):
        return _no_scope("blocked_by_non_technical_path")

    session_payload = _session_payload(agent_input)
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

    if active_service_name and query_mentions_scope(query, active_service_name):
        return _resolved_scope(
            "service",
            "current",
            active_service_name,
            "query_mentions_active_service_name",
        )
    if active_product_name and query_mentions_scope(query, active_product_name):
        return _resolved_scope(
            "product",
            "current",
            active_product_name,
            "query_mentions_active_product_name",
        )

    if _is_continuation_turn(agent_input):
        active_entity = _active_entity(agent_input)
        prior_active_entity = _prior_active_entity(agent_input)
        current_active_entity_kind = str(active_entity.get("entity_kind") or "").strip()
        prior_active_entity_kind = str(prior_active_entity.get("entity_kind") or "").strip()

        if current_active_entity_kind in {"service", "product"}:
            active_entity_kind = current_active_entity_kind
        elif prior_active_entity_kind in {"service", "product"}:
            active_entity_kind = prior_active_entity_kind
        elif active_service_name:
            active_entity_kind = "service"
        elif active_product_name:
            active_entity_kind = "product"
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

    # An active service is a strong anchor: any technical-ish query (already
    # past the non_technical_fallback gate above) should retrieve within that
    # service's scope even on cold-start turns without a follow-up marker.
    if active_service_name:
        intent_bucket = detect_intent_bucket(query, _semantic_intent(agent_input))
        return _resolved_scope(
            "service",
            "active",
            active_service_name,
            f"active_service_retrieval_fallback_{intent_bucket}",
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
            },
            "product_lookup_keys": {
                "service_names": [],
                "product_names": [],
                "catalog_numbers": [],
            },
        }
        if not has_current_scope
        else {
            "query": query,
            "entities": {
                "product_names": ["current_scope_present"],
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
    "canonicalize_service_name",
    "detect_intent_bucket",
    "get_bucket_mode",
    "has_current_scope",
    "is_service_scoped_follow_up",
    "normalize_scope_query",
    "query_has_product_scope_marker",
    "query_matches_non_technical_fallback_path",
    "query_has_service_scope_marker",
    "query_mentions_scope",
    "resolve_active_scope",
    "resolve_current_scope",
    "resolve_effective_scope",
    "should_fallback_to_active_service_context",
]
