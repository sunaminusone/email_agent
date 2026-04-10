from __future__ import annotations

from src.response.models import ComposedResponse, ResponseInput, ResponsePlan


def render_handoff_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    message = "This request needs human review before a final email reply is prepared."
    if response_input.execution_run.reason:
        message = f"{message} Reason: {response_input.execution_run.reason}"

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
