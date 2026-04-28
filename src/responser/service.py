from __future__ import annotations

from src.responser.blocks import build_content_blocks
from src.responser.composer import compose_final_response
from src.responser.models import (
    ComposedResponse,
    ContentBlock,
    ResponseBundle,
    ResponseInput,
    ResponsePlan,
)
from src.responser.planner import build_response_plan
from src.responser.renderers import (
    render_acknowledgement_response,
    render_answer_response,
    render_clarification_response,
    render_handoff_response,
    render_knowledge_response,
    render_partial_answer_response,
    render_termination_response,
)
from src.responser.renderers.csr_draft import render_csr_draft_response


def plan_response(response_input: ResponseInput) -> tuple[ResponsePlan, list[ContentBlock]]:
    content_blocks = build_content_blocks(response_input)
    response_plan = build_response_plan(response_input, content_blocks)
    return response_plan, content_blocks


def compose_response(response_input: ResponseInput) -> tuple[ComposedResponse, ResponsePlan]:
    response_plan, _ = plan_response(response_input)
    draft = _render_response(response_input, response_plan)
    return compose_final_response(draft, response_plan, locale=response_input.locale), response_plan


def build_response_bundle(response_input: ResponseInput) -> ResponseBundle:
    response_plan, content_blocks = plan_response(response_input)
    draft = _render_response(response_input, response_plan)
    composed_response = compose_final_response(draft, response_plan, locale=response_input.locale)
    response_path = str(composed_response.debug_info.get("response_path", "deterministic"))

    # Topic derivation — inlined from former resolution.py
    if response_plan.response_mode in {"clarification", "handoff"}:
        response_topic = response_plan.response_mode
    else:
        response_topic = response_plan.answer_focus or response_plan.response_mode

    # Content summary — inlined from former resolution.py
    response_content_summary = " ".join(
        block.body.strip() for block in content_blocks if block.body
    ).strip()

    return ResponseBundle(
        composed_response=composed_response,
        response_plan=response_plan,
        response_topic=response_topic,
        response_content_summary=response_content_summary,
        response_path=response_path,
    )


def _render_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    # CSR mode: always use the draft renderer regardless of response_mode.
    # The seven legacy renderers (clarification, handoff, knowledge, etc.)
    # are kept for now as importable artefacts but no longer dispatched —
    # they assume customer-facing output, which CSR mode invalidates.
    return render_csr_draft_response(response_input, response_plan)
