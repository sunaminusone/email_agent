from __future__ import annotations

from src.response.models import ComposedResponse, ResponseInput, ResponsePlan


def render_acknowledgement_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    message = "Understood."
    if response_input.query:
        message = f"Understood. I noted: {response_input.query}"

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
