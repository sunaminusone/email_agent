from __future__ import annotations

from src.common.messages import get_message
from src.responser.models import ComposedResponse, ResponseInput, ResponsePlan


def render_clarification_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    locale = response_input.locale
    clarification = response_input.clarification
    message = get_message("response_clarification_default", locale)
    if clarification is not None and clarification.prompt:
        message = clarification.prompt

    return ComposedResponse(
        message=message,
        response_type="clarification",
        content_blocks=[
            *response_plan.primary_content_blocks,
            *response_plan.supporting_content_blocks,
        ],
        debug_info={
            "response_mode": response_plan.response_mode,
            "reason": response_plan.reason,
            "missing_information": (
                list(clarification.missing_information) if clarification is not None else []
            ),
        },
    )
