from __future__ import annotations

from src.memory.models import MemorySnapshot, MemoryUpdate, ResponseMemory


def apply_response_memory_update(snapshot: MemorySnapshot, update: MemoryUpdate) -> MemorySnapshot:
    next_snapshot = snapshot.model_copy(deep=True)
    explicit_fields = update.model_fields_set

    if "response_memory" in explicit_fields and update.response_memory is not None:
        response_memory = update.response_memory.model_copy(deep=True)
    else:
        response_memory = next_snapshot.response_memory.model_copy(deep=True)

    if update.soft_reset_current_topic:
        response_memory = response_memory.model_copy(
            update={
                "revealed_attributes": [],
                "last_tool_results": [],
            }
        )

    if "mark_revealed_attributes" in explicit_fields:
        revealed = list(response_memory.revealed_attributes)
        for attribute in update.mark_revealed_attributes:
            cleaned = str(attribute).strip()
            if cleaned and cleaned not in revealed:
                revealed.append(cleaned)
        response_memory.revealed_attributes = revealed[-10:]

    if "set_last_tool_results" in explicit_fields:
        response_memory.last_tool_results = [dict(item) for item in update.set_last_tool_results][-5:]

    if "set_last_response_topics" in explicit_fields:
        response_memory.last_response_topics = [
            str(topic).strip()
            for topic in update.set_last_response_topics
            if str(topic).strip()
        ][-5:]

    if "set_last_demand_type" in explicit_fields and update.set_last_demand_type is not None:
        response_memory.last_demand_type = update.set_last_demand_type

    if "set_last_demand_flags" in explicit_fields and update.set_last_demand_flags:
        response_memory.last_demand_flags = list(update.set_last_demand_flags)

    next_snapshot.response_memory = response_memory
    return next_snapshot


def build_response_memory(
    *,
    revealed_attributes: list[str],
    last_tool_results: list[dict],
    last_response_topics: list[str],
    last_demand_type: str = "general",
    last_demand_flags: list[str] | None = None,
) -> ResponseMemory:
    return ResponseMemory(
        revealed_attributes=revealed_attributes[-10:],
        last_tool_results=last_tool_results[-5:],
        last_response_topics=last_response_topics[-5:],
        last_demand_type=last_demand_type,
        last_demand_flags=list(last_demand_flags) if last_demand_flags else [],
    )
