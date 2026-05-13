from __future__ import annotations

from src.responser.blocks import build_content_blocks
from src.responser.csr.composer import render_csr_draft_response
from src.responser.models import (
    ComposedResponse,
    ContentBlock,
    ResponseBundle,
    ResponseInput,
    ResponsePlan,
)
from src.responser.planner import build_response_plan


def plan_response(response_input: ResponseInput) -> tuple[ResponsePlan, list[ContentBlock]]:
    content_blocks = build_content_blocks(response_input)
    response_plan = build_response_plan(response_input, content_blocks)
    return response_plan, content_blocks


def compose_response(response_input: ResponseInput) -> tuple[ComposedResponse, ResponsePlan]:
    # Compatibility wrapper for tests and older call sites that only need
    # the composed response plus its plan, not the derived bundle metadata.
    bundle = build_response_bundle(response_input)
    return bundle.composed_response, bundle.response_plan


def build_response_bundle(response_input: ResponseInput) -> ResponseBundle:
    response_plan, content_blocks, composed_response = _build_response_artifacts(response_input)
    return assemble_response_bundle(
        composed_response=composed_response,
        response_plan=response_plan,
        content_blocks=content_blocks,
    )


def assemble_response_bundle(
    *,
    composed_response: ComposedResponse,
    response_plan: ResponsePlan,
    content_blocks: list[ContentBlock],
) -> ResponseBundle:
    """Assemble the final bundle from an already-rendered composed response.
    Streaming callers render via ``stream_csr_response`` and then call this
    to get topic / summary / path metadata without re-running the LLM."""
    composed_response.debug_info.setdefault("response_path", "csr_renderer_direct")
    response_path = str(composed_response.debug_info.get("response_path", "csr_renderer_direct"))

    # Topic derivation: answer_focus already encodes both control topics
    # (missing_information / human_review / conversation_close /
    # conversation_control) and informational topics (knowledge_lookup /
    # commercial_or_operational_lookup / etc.), so it is the authoritative
    # source for memory continuity and downstream routing context.
    response_topic = response_plan.answer_focus

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


def _build_response_artifacts(
    response_input: ResponseInput,
) -> tuple[ResponsePlan, list[ContentBlock], ComposedResponse]:
    response_plan, content_blocks = plan_response(response_input)
    composed_response = _render_response(response_input, response_plan)
    return response_plan, content_blocks, composed_response


def _render_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    composed_response = render_csr_draft_response(response_input, response_plan)
    composed_response.debug_info.setdefault("response_path", "csr_renderer_direct")
    return composed_response
