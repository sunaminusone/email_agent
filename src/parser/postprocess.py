from typing import Any

from src.parser.intent_resolution import resolve_intent_overrides
from src.schemas import ParsedResult


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


def postprocess_parsed_result(
    parsed: ParsedResult,
    *,
    user_query: str,
    conversation_history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> ParsedResult:
    conversation_history = conversation_history or []
    attachments = attachments or []

    parsed = parsed.model_copy(
        update={
            "normalized_query": (parsed.normalized_query or user_query or "").strip(),
            "entities": parsed.entities.model_copy(
                update={
                    "product_names": _dedupe(parsed.entities.product_names),
                    "catalog_numbers": _dedupe(parsed.entities.catalog_numbers),
                    "service_names": _dedupe(parsed.entities.service_names),
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
    return parsed
