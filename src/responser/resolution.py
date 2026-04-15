from __future__ import annotations

from src.responser.models import ContentBlock, ResponsePlan, ResponseResolution


def build_response_resolution(
    response_plan: ResponsePlan,
    content_blocks: list[ContentBlock],
) -> ResponseResolution:
    primary_block = response_plan.primary_content_blocks[0] if response_plan.primary_content_blocks else None
    primary_action_type = str(primary_block.title or primary_block.block_type) if primary_block is not None else ""

    answer_focus = _infer_answer_focus(response_plan, content_blocks)
    supporting_action_types = [
        str(block.title or block.block_type)
        for block in content_blocks[1:]
    ]

    return ResponseResolution(
        topic_type=response_plan.response_mode,
        answer_focus=answer_focus,
        primary_action_type=primary_action_type,
        supporting_action_types=supporting_action_types,
        reply_style="direct",
        should_ask_clarification=response_plan.response_mode == "clarification",
    )


def derive_response_topic(
    response_plan: ResponsePlan,
    response_resolution: ResponseResolution,
) -> str:
    if response_plan.response_mode in {"clarification", "handoff"}:
        return response_plan.response_mode
    return response_resolution.answer_focus or response_plan.response_mode


def summarize_content_blocks(content_blocks: list[ContentBlock]) -> str:
    return " ".join(block.body.strip() for block in content_blocks if block.body).strip()


def _infer_answer_focus(response_plan: ResponsePlan, content_blocks: list[ContentBlock]) -> str:
    if response_plan.response_mode == "clarification":
        return "missing_information"
    if response_plan.response_mode == "handoff":
        return "human_review"
    if response_plan.response_mode == "acknowledgement":
        return "conversation_control"
    if response_plan.response_mode == "termination":
        return "conversation_close"

    block_types = {block.block_type for block in content_blocks}
    if "technical_snippets" in block_types:
        return "knowledge_lookup"
    if "document_artifacts" in block_types:
        return "document_lookup"
    if "structured_facts" in block_types:
        return "commercial_or_operational_lookup"
    return "general_support"
