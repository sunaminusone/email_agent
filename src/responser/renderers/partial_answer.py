"""Renderer for partial_answer mode.

Used when multiple intent groups are present and some are resolved while
others still need clarification.  Combines the answered portion with a
clarification prompt for the remaining groups.
"""
from __future__ import annotations

from src.common.messages import get_message
from src.responser.models import ComposedResponse, ContentBlock, ResponseInput, ResponsePlan


def render_partial_answer_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    locale = response_input.locale
    blocks = [
        *response_plan.primary_content_blocks,
        *response_plan.supporting_content_blocks,
    ]

    # Build the answered portion from resolved groups
    message_parts: list[str] = []
    if blocks:
        message_parts.append(get_message("response_partial_answer", locale))
        for block in blocks[:3]:
            if block.body:
                message_parts.append(block.body)

    # Build clarification portion from pending groups
    for outcome in response_input.group_outcomes:
        if outcome.status == "needs_clarification":
            clarification = outcome.route_decision.clarification
            prompt = clarification.prompt if clarification is not None else ""
            intent_label = outcome.group.intent or outcome.group.object_type or "unknown"
            if prompt:
                message_parts.append(
                    get_message("response_partial_clarification", locale, intent=intent_label, prompt=prompt)
                )

    message = " ".join(part.strip() for part in message_parts if part.strip()).strip()

    return ComposedResponse(
        message=message,
        response_type="partial_answer",
        content_blocks=blocks,
        debug_info={
            "response_mode": response_plan.response_mode,
            "reason": response_plan.reason,
            "resolved_groups": len([o for o in response_input.group_outcomes if o.status == "resolved"]),
            "clarification_groups": len([o for o in response_input.group_outcomes if o.status == "needs_clarification"]),
        },
    )
