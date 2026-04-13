from __future__ import annotations

from src.common.messages import get_message
from src.response.models import ComposedResponse, ResponseInput, ResponsePlan


def render_termination_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    locale = response_input.locale
    return ComposedResponse(
        message=get_message("response_termination", locale),
        response_type="termination",
        content_blocks=[
            *response_plan.primary_content_blocks,
            *response_plan.supporting_content_blocks,
        ],
        debug_info={
            "response_mode": response_plan.response_mode,
            "reason": response_plan.reason,
        },
    )
