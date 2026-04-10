from __future__ import annotations

from src.response.blocks import build_content_blocks
from src.response.composer import compose_final_response
from src.response.models import (
    ComposedResponse,
    ContentBlock,
    ResponseBundle,
    ResponseInput,
    ResponsePlan,
)
from src.response.resolution import (
    build_response_resolution,
    derive_response_topic,
    summarize_content_blocks,
)
from src.response.planner import build_response_plan
from src.response.renderers import (
    render_acknowledgement_response,
    render_answer_response,
    render_clarification_response,
    render_handoff_response,
    render_termination_response,
)


def plan_response(response_input: ResponseInput) -> tuple[ResponsePlan, list[ContentBlock]]:
    content_blocks = build_content_blocks(response_input)
    response_plan = build_response_plan(response_input, content_blocks)
    return response_plan, content_blocks


def compose_response(response_input: ResponseInput) -> tuple[ComposedResponse, ResponsePlan]:
    response_plan, _ = plan_response(response_input)
    draft = _render_response(response_input, response_plan)
    return compose_final_response(draft, response_plan), response_plan


def build_response_bundle(response_input: ResponseInput) -> ResponseBundle:
    response_plan, content_blocks = plan_response(response_input)
    draft = _render_response(response_input, response_plan)
    composed_response = compose_final_response(draft, response_plan)
    response_resolution = build_response_resolution(response_plan, content_blocks)
    response_topic = derive_response_topic(response_plan, response_resolution)
    response_path = str(composed_response.debug_info.get("response_path", "deterministic"))

    return ResponseBundle(
        composed_response=composed_response,
        response_plan=response_plan,
        response_resolution=response_resolution,
        response_topic=response_topic,
        response_content_summary=summarize_content_blocks(content_blocks),
        response_path=response_path,
    )


def _render_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    mode = response_plan.response_mode
    if mode == "clarification":
        return render_clarification_response(response_input, response_plan)
    if mode == "handoff":
        return render_handoff_response(response_input, response_plan)
    if mode == "acknowledgement":
        return render_acknowledgement_response(response_input, response_plan)
    if mode == "termination":
        return render_termination_response(response_input, response_plan)
    return render_answer_response(response_input, response_plan)
