from __future__ import annotations

from src.ingestion.demand_profile import FLAG_DEMAND, is_truly_mixed
from src.memory.models import MemoryUpdate, ResponseMemory
from src.memory.response_memory import build_response_memory
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
    # Multi-group: some resolved + some need clarification → partial_answer
    if response_input.group_outcomes:
        resolved = [o for o in response_input.group_outcomes if o.status == "resolved"]
        clarifying = [o for o in response_input.group_outcomes if o.status == "needs_clarification"]
        handoffs = [o for o in response_input.group_outcomes if o.status == "needs_handoff"]

        if handoffs:
            return "handoff"
        if resolved and clarifying:
            return "partial_answer"
        if not resolved and clarifying:
            return "clarification"

    if response_input.action == "clarify":
        return "clarification"

    if response_input.action == "handoff":
        return "handoff"

    dialogue_act = response_input.dialogue_act.act

    # No tool results and not a closing act → LLM knowledge answer
    if not response_input.execution_result.executed_calls and dialogue_act != "closing":
        return "knowledge_answer"

    # v3 closing act: distinguish termination vs acknowledgement via matched_signals
    if dialogue_act == "closing":
        if "terminate_pattern" in response_input.dialogue_act.matched_signals:
            return "termination"
        if not _has_informational_blocks(content_blocks):
            return "acknowledgement"

    # Demand-aware: mixed demand → hybrid; single-focus → direct
    if _is_demand_mixed(response_input):
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
    return has_object_block and response_input.dialogue_act.act == "inquiry"


def _build_memory_update(
    *,
    response_mode: str,
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

    topic = response_mode
    if topic and topic not in last_topics:
        last_topics.append(topic)
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
    if response_mode == "partial_answer":
        return "Some intent groups resolved while others still need clarification."
    if response_mode == "hybrid_answer":
        dp = response_input.demand_profile
        if dp is not None:
            demands = [dp.primary_demand, *dp.secondary_demands]
            return f"User demand spans multiple families ({', '.join(demands)})."
        return "User demand is mixed across multiple families."
    if response_mode == "knowledge_answer":
        return "No tool results available; answering from LLM knowledge."
    return "Single-focus demand; one grounded answer path is sufficient."


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


def _is_demand_mixed(response_input: ResponseInput) -> bool:
    """Check if the user's demand is truly mixed (cross-family).

    Uses DemandProfile as the single source — not block count.
    A pure technical question producing structured_facts + technical_snippets
    is still single-focus (direct_answer), not hybrid.
    """
    dp = response_input.demand_profile
    if dp is None:
        return False
    return is_truly_mixed(dp.primary_demand, dp.secondary_demands)


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
