from __future__ import annotations

from src.ingestion.demand_profile import FLAG_DEMAND
from src.memory.models import MemoryUpdate, ResponseMemory
from src.memory.response_memory import build_response_memory
from src.responser.models import ContentBlock, ResponseInput, ResponsePlan


def build_response_plan(
    response_input: ResponseInput,
    content_blocks: list[ContentBlock],
) -> ResponsePlan:
    answer_focus = _infer_answer_focus(response_input, content_blocks)
    topic_continuing = _is_topic_continuing(response_input.response_memory, answer_focus)
    primary_blocks, supporting_blocks = _split_blocks(
        content_blocks, topic_continuing=topic_continuing,
    )

    memory_update = _build_memory_update(
        answer_focus=answer_focus,
        response_input=response_input,
        content_blocks=content_blocks,
    )

    return ResponsePlan(
        answer_focus=answer_focus,
        primary_content_blocks=primary_blocks,
        supporting_content_blocks=supporting_blocks,
        should_acknowledge_object=_should_acknowledge_object(
            response_input, content_blocks, topic_continuing=topic_continuing,
        ),
        memory_update=memory_update,
        reason="",
    )


def _split_blocks(
    content_blocks: list[ContentBlock],
    *,
    topic_continuing: bool = False,
) -> tuple[list[ContentBlock], list[ContentBlock]]:
    priority_order = {
        "object_summary": 0,
        "structured_facts": 1,
        "technical_snippets": 2,
        "document_artifacts": 3,
        "supporting_records": 4,
    }
    # Consecutive same-topic turn: demote object_summary so informational
    # blocks surface first — the user already knows which object we're on.
    if topic_continuing:
        priority_order["object_summary"] = 5

    ordered_blocks = sorted(content_blocks, key=lambda block: priority_order.get(block.block_type, 99))
    return ordered_blocks[:2], ordered_blocks[2:]


def _should_acknowledge_object(
    response_input: ResponseInput,
    content_blocks: list[ContentBlock],
    *,
    topic_continuing: bool = False,
) -> bool:
    if response_input.resolved_object_state is None:
        return False
    # Consecutive same-topic: user already knows the object context, skip the
    # "关于 XX 产品..." opener to avoid repetition.
    if topic_continuing:
        return False
    has_object_block = any(block.block_type == "object_summary" for block in content_blocks)
    return has_object_block and response_input.dialogue_act.act == "inquiry"


def _build_memory_update(
    *,
    answer_focus: str,
    response_input: ResponseInput,
    content_blocks: list[ContentBlock],
) -> MemoryUpdate:
    existing_memory = response_input.response_memory or ResponseMemory()
    revealed_attributes = list(existing_memory.revealed_attributes)
    last_topics = list(existing_memory.last_response_topics)
    last_tool_results = [
        {
            "tool_name": call.tool_name,
            "status": call.status,
            "call_id": call.call_id,
        }
        for call in response_input.execution_result.executed_calls
        if call.status != "error"
    ]

    block_types = [block.block_type for block in content_blocks]
    for block_type in block_types:
        if block_type not in revealed_attributes:
            revealed_attributes.append(block_type)

    if answer_focus and answer_focus not in last_topics:
        last_topics.append(answer_focus)
    last_topics = last_topics[-5:]

    # Extract demand for memory — only store primary demand's flags
    demand_type, demand_flags = _extract_primary_demand(response_input)

    response_memory = build_response_memory(
        revealed_attributes=revealed_attributes,
        last_tool_results=last_tool_results or list(existing_memory.last_tool_results),
        last_response_topics=last_topics,
        last_demand_type=demand_type,
        last_demand_flags=demand_flags,
    )

    soft_reset = (
        response_input.dialogue_act.act == "closing"
        and "terminate_pattern" in response_input.dialogue_act.matched_signals
    )
    return MemoryUpdate(
        response_memory=response_memory,
        soft_reset_current_topic=soft_reset,
    )


def _extract_primary_demand(response_input: ResponseInput) -> tuple[str, list[str]]:
    """Extract primary demand type and its corresponding flags for memory.

    Only stores flags that belong to the primary demand type, so a mixed
    query (technical + commercial) doesn't pollute continuity with the
    secondary demand's flags.
    """
    dp = response_input.demand_profile
    if dp is None:
        return "general", []

    primary = dp.primary_demand
    # Filter: only flags whose demand type matches the primary
    primary_flags = [
        flag for flag in dp.active_request_flags
        if FLAG_DEMAND.get(flag, "general") == primary
    ]
    return primary, primary_flags


def _has_informational_blocks(content_blocks: list[ContentBlock]) -> bool:
    return any(
        block.block_type
        in {"structured_facts", "technical_snippets", "document_artifacts", "supporting_records"}
        for block in content_blocks
    )


INFORMATIONAL_TOPICS = frozenset({
    "knowledge_lookup",
    "document_lookup",
    "commercial_or_operational_lookup",
    "general_support",
})


def _is_topic_continuing(response_memory: ResponseMemory | None, current_focus: str) -> bool:
    """Check whether the current answer_focus repeats the most recent topic.

    Only informational topics count — control topics like "conversation_close"
    or "missing_information" should not trigger continuity behaviour.
    """
    if response_memory is None or not response_memory.last_response_topics:
        return False
    if current_focus not in INFORMATIONAL_TOPICS:
        return False
    return response_memory.last_response_topics[-1] == current_focus


def _infer_answer_focus(response_input: ResponseInput, content_blocks: list[ContentBlock]) -> str:
    # Multi-group routing outcomes take precedence — they reflect what the
    # agent loop actually decided per intent group, before service.py coerces
    # the top-level action to "execute" under the v4 CSR invariant.
    if response_input.group_outcomes:
        statuses = {o.status for o in response_input.group_outcomes}
        if "needs_handoff" in statuses:
            return "human_review"
        if "needs_clarification" in statuses:
            return "missing_information"

    if response_input.action == "clarify":
        return "missing_information"
    if response_input.action == "handoff":
        return "human_review"

    if response_input.dialogue_act.act == "closing":
        if "terminate_pattern" in response_input.dialogue_act.matched_signals:
            return "conversation_close"
        if not _has_informational_blocks(content_blocks):
            return "conversation_control"

    block_types = {block.block_type for block in content_blocks}
    if "technical_snippets" in block_types:
        return "knowledge_lookup"
    if "document_artifacts" in block_types:
        return "document_lookup"
    if "structured_facts" in block_types:
        return "commercial_or_operational_lookup"
    return "general_support"
