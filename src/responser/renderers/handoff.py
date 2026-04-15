from __future__ import annotations

from src.common.messages import get_message
from src.responser.models import ComposedResponse, ResponseInput, ResponsePlan


def render_handoff_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    locale = response_input.locale
    message = get_message("response_handoff", locale)
    if response_input.execution_result.reason:
        message = get_message(
            "response_handoff_reason", locale,
            base=message, reason=response_input.execution_result.reason,
        )

    return ComposedResponse(
        message=message,
        response_type="handoff",
        content_blocks=[
            *response_plan.primary_content_blocks,
            *response_plan.supporting_content_blocks,
        ],
        debug_info={
            "response_mode": response_plan.response_mode,
            "reason": response_plan.reason,
        },
    )
