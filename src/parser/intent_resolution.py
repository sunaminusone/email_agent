from src.schemas import ParsedResult


def resolve_intent_overrides(parsed: ParsedResult, *, user_query: str) -> ParsedResult:
    normalized_query = (parsed.normalized_query or user_query or "").strip().lower()
    context = parsed.context
    flags = parsed.request_flags

    primary_intent = context.primary_intent
    confidence = context.intent_confidence or 0.0

    if flags.needs_invoice or flags.needs_order_status or "invoice" in normalized_query or "order" in normalized_query:
        primary_intent = "order_support"
        confidence = max(confidence, 0.85)
    elif flags.needs_documentation:
        primary_intent = "documentation_request"
        confidence = max(confidence, 0.85)
    elif flags.needs_price or flags.needs_quote:
        primary_intent = "pricing_question"
        confidence = max(confidence, 0.85)
    elif flags.needs_timeline:
        primary_intent = "timeline_question"
        confidence = max(confidence, 0.8)
    elif flags.needs_customization:
        primary_intent = "customization_request"
        confidence = max(confidence, 0.8)
    elif flags.needs_troubleshooting:
        primary_intent = "troubleshooting"
        confidence = max(confidence, 0.8)
    elif flags.needs_availability and not parsed.entities.order_numbers:
        primary_intent = "product_inquiry"
        confidence = max(confidence, 0.75)

    if primary_intent == context.primary_intent and confidence == context.intent_confidence:
        return parsed

    return parsed.model_copy(
        update={
            "context": context.model_copy(
                update={
                    "primary_intent": primary_intent,
                    "intent_confidence": confidence,
                }
            )
        }
    )
