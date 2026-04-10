from __future__ import annotations

from src.memory.models import MemoryUpdate, ResponseMemory
from src.response.models import ContentBlock, ResponseInput, ResponsePlan


def build_response_plan(
    response_input: ResponseInput,
    content_blocks: list[ContentBlock],
) -> ResponsePlan:
    response_mode = _select_response_mode(response_input, content_blocks)
    primary_blocks, supporting_blocks = _split_blocks(response_mode, content_blocks)

    memory_update = _build_memory_update(
        response_mode=response_mode,
        response_input=response_input,
        content_blocks=content_blocks,
    )

    return ResponsePlan(
        response_mode=response_mode,
        primary_content_blocks=primary_blocks,
        supporting_content_blocks=supporting_blocks,
        should_use_llm_rewrite=_should_use_llm_rewrite(response_mode, primary_blocks, supporting_blocks),
        should_acknowledge_object=_should_acknowledge_object(response_input, content_blocks),
        memory_update=memory_update,
        reason=_build_reason(response_mode, response_input, content_blocks),
    )


def _select_response_mode(
    response_input: ResponseInput,
    content_blocks: list[ContentBlock],
) -> str:
    if response_input.route_name == "clarification" or response_input.execution_run.intent.needs_clarification:
        return "clarification"

    if response_input.route_name == "handoff" or response_input.execution_run.intent.handoff_required:
        return "handoff"

    dialogue_act = response_input.dialogue_act.act
    if dialogue_act == "UNKNOWN":
        dialogue_act = response_input.execution_run.intent.dialogue_act.act
    if dialogue_act == "TERMINATE":
        return "termination"
    if dialogue_act == "ACKNOWLEDGE" and not _has_informational_blocks(content_blocks):
        return "acknowledgement"

    informational_blocks = [
        block
        for block in content_blocks
        if block.block_type not in {"object_summary", "clarification_options", "handoff_notice"}
    ]
    if len(informational_blocks) > 1:
        return "hybrid_answer"
    return "direct_answer"


def _split_blocks(response_mode: str, content_blocks: list[ContentBlock]) -> tuple[list[ContentBlock], list[ContentBlock]]:
    if response_mode in {"clarification", "handoff", "acknowledgement", "termination"}:
        return list(content_blocks[:1]), list(content_blocks[1:])

    priority_order = {
        "object_summary": 0,
        "structured_facts": 1,
        "technical_snippets": 2,
        "document_artifacts": 3,
        "supporting_records": 4,
    }
    ordered_blocks = sorted(content_blocks, key=lambda block: priority_order.get(block.block_type, 99))
    return ordered_blocks[:2], ordered_blocks[2:]


def _should_acknowledge_object(response_input: ResponseInput, content_blocks: list[ContentBlock]) -> bool:
    if response_input.resolved_object_state is None:
        return False
    has_object_block = any(block.block_type == "object_summary" for block in content_blocks)
    return has_object_block and response_input.dialogue_act.act in {"ELABORATE", "INQUIRY", "UNKNOWN"}


def _build_memory_update(
    *,
    response_mode: str,
    response_input: ResponseInput,
    content_blocks: list[ContentBlock],
) -> MemoryUpdate:
    existing_memory = response_input.response_memory or ResponseMemory()
    revealed_attributes = list(existing_memory.revealed_attributes)
    last_topics = list(existing_memory.last_response_topics)

    block_types = [block.block_type for block in content_blocks]
    for block_type in block_types:
        if block_type not in revealed_attributes:
            revealed_attributes.append(block_type)

    topic = response_mode
    if topic and topic not in last_topics:
        last_topics.append(topic)
    last_topics = last_topics[-5:]

    response_memory = ResponseMemory(
        revealed_attributes=revealed_attributes[-10:],
        last_tool_results=list(existing_memory.last_tool_results),
        last_response_topics=last_topics,
    )

    return MemoryUpdate(
        response_memory=response_memory,
        soft_reset_current_topic=response_mode == "termination",
    )


def _build_reason(response_mode: str, response_input: ResponseInput, content_blocks: list[ContentBlock]) -> str:
    if response_mode == "clarification":
        return "Execution remains blocked until missing information is resolved."
    if response_mode == "handoff":
        return "The request requires human review or a manual workflow."
    if response_mode == "termination":
        return "The user asked to stop the current topic."
    if response_mode == "acknowledgement":
        return "The turn is a short acknowledgement without a new informational ask."
    if response_mode == "hybrid_answer":
        return f"The result includes multiple grounded content families ({len(content_blocks)} blocks)."
    return "A single grounded answer path is sufficient for this execution result."


def _has_informational_blocks(content_blocks: list[ContentBlock]) -> bool:
    return any(
        block.block_type
        in {"structured_facts", "technical_snippets", "document_artifacts", "supporting_records"}
        for block in content_blocks
    )


def _should_use_llm_rewrite(
    response_mode: str,
    primary_blocks: list[ContentBlock],
    supporting_blocks: list[ContentBlock],
) -> bool:
    if response_mode not in {"direct_answer", "hybrid_answer"}:
        return False
    all_blocks = [*primary_blocks, *supporting_blocks]
    return _has_informational_blocks(all_blocks)
