from typing import Any

from src.parser.intent_resolution import resolve_intent_overrides
from src.schemas import ParsedResult


_DOCUMENT_TERMS = (
    "datasheet",
    "brochure",
    "protocol",
    "manual",
    "coa",
    "sds",
    "technical file",
)

_PRODUCT_INFO_INTRO_PATTERNS = (
    "tell me about",
    "what is",
    "what are",
    "can you tell me about",
)

_TRACKING_TERMS = (
    "tracking",
    "track",
    "where is my order",
    "track my order",
)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
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


def _canonicalize_values(values: list[str], canonicalizer: Any) -> list[str]:
    canonicalized: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        canonicalized.append(str(canonicalizer(cleaned) or "").strip())
    return canonicalized


def _canonicalize_product_names(values: list[str]) -> list[str]:
    from src.catalog.product_registry import canonicalize_product_name

    return _canonicalize_values(values, canonicalize_product_name)


def _canonicalize_service_names(values: list[str]) -> list[str]:
    from src.conversation.service_registry import canonicalize_service_name

    return _canonicalize_values(values, canonicalize_service_name)


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _should_force_product_inquiry(parsed: ParsedResult, normalized_query: str) -> bool:
    if parsed.context.primary_intent != "documentation_request":
        return False
    if not parsed.entities.product_names or parsed.entities.catalog_numbers or parsed.entities.service_names:
        return False
    if any(term in normalized_query for term in _DOCUMENT_TERMS):
        return False
    return any(normalized_query.startswith(pattern) for pattern in _PRODUCT_INFO_INTRO_PATTERNS)


def _apply_intent_and_flag_corrections(parsed: ParsedResult, normalized_query: str) -> ParsedResult:
    updated = parsed

    if _should_force_product_inquiry(updated, normalized_query):
        updated = updated.model_copy(
            update={
                "context": updated.context.model_copy(update={"primary_intent": "product_inquiry"}),
                "request_flags": updated.request_flags.model_copy(
                    update={"needs_documentation": False, "needs_availability": True}
                ),
            }
        )

    if updated.entities.order_numbers and any(term in normalized_query for term in _TRACKING_TERMS):
        updated = updated.model_copy(
            update={
                "request_flags": updated.request_flags.model_copy(
                    update={"needs_shipping_info": True}
                )
            }
        )

    return updated


def postprocess_parsed_result(
    parsed: ParsedResult,
    *,
    user_query: str,
    conversation_history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    ) -> ParsedResult:
    conversation_history = conversation_history or []
    attachments = attachments or []
    normalized_query = _normalize_text(parsed.normalized_query or user_query or "")

    parsed = parsed.model_copy(
        update={
            "normalized_query": (parsed.normalized_query or user_query or "").strip(),
            "entities": parsed.entities.model_copy(
                update={
                    "product_names": _dedupe(
                        _canonicalize_product_names(parsed.entities.product_names)
                    ),
                    "catalog_numbers": _dedupe(parsed.entities.catalog_numbers),
                    "service_names": _dedupe(
                        _canonicalize_service_names(parsed.entities.service_names)
                    ),
                    "targets": _dedupe(parsed.entities.targets),
                    "species": _dedupe(parsed.entities.species),
                    "applications": _dedupe(parsed.entities.applications),
                    "order_numbers": _dedupe(parsed.entities.order_numbers),
                    "document_names": _dedupe(parsed.entities.document_names),
                    "company_names": _dedupe(parsed.entities.company_names),
                }
            ),
            "missing_information": _dedupe(parsed.missing_information),
        }
    )

    if attachments and not parsed.tool_hints.requires_file_lookup:
        if parsed.request_flags.needs_documentation or parsed.request_flags.needs_protocol:
            parsed = parsed.model_copy(
                update={
                    "tool_hints": parsed.tool_hints.model_copy(
                        update={"requires_file_lookup": True}
                    )
                }
            )

    if conversation_history and parsed.context.query_type == "question":
        latest_role = str(conversation_history[-1].get("role", "")).lower()
        if latest_role == "assistant" and parsed.context.primary_intent == "unknown":
            parsed = parsed.model_copy(
                update={
                    "context": parsed.context.model_copy(update={"primary_intent": "follow_up"})
                }
            )

    parsed = resolve_intent_overrides(parsed, user_query=user_query)
    parsed = _apply_intent_and_flag_corrections(parsed, normalized_query)
    return parsed
