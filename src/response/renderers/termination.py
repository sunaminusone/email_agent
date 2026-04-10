from __future__ import annotations

from src.response.models import ComposedResponse, ResponseInput, ResponsePlan


def render_termination_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    return ComposedResponse(
        message="Understood. I will stop here on this topic.",
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
