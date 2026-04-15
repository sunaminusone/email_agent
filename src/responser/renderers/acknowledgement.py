from __future__ import annotations

from src.common.messages import get_message
from src.responser.models import ComposedResponse, ResponseInput, ResponsePlan


def render_acknowledgement_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    locale = response_input.locale
    if response_input.query:
        message = get_message("response_acknowledgement_noted", locale, query=response_input.query)
    else:
        message = get_message("response_acknowledgement", locale)

    return ComposedResponse(
        message=message,
        response_type="acknowledgement",
        content_blocks=[
            *response_plan.primary_content_blocks,
            *response_plan.supporting_content_blocks,
        ],
        debug_info={
            "response_mode": response_plan.response_mode,
            "reason": response_plan.reason,
        },
    )
