from __future__ import annotations

from typing import Any

from src.memory.clarification_memory import apply_clarification_memory_update
from src.memory.models import MemorySnapshot, MemoryUpdate
from src.memory.object_memory import apply_object_memory_update
from src.memory.response_memory import apply_response_memory_update
from src.memory.thread_memory import apply_thread_memory_update


def load_memory_snapshot(prior_state: Any | None = None, *, thread_id: str | None = None) -> MemorySnapshot:
    if isinstance(prior_state, MemorySnapshot):
        snapshot = prior_state.model_copy(deep=True)
    else:
        source = prior_state if isinstance(prior_state, dict) else {}
        snapshot_source = source.get("memory_snapshot", source) if isinstance(source.get("memory_snapshot"), dict) else source
        snapshot = MemorySnapshot.model_validate(
            {
                "thread_memory": snapshot_source.get("thread_memory", {}) or {},
                "object_memory": snapshot_source.get("object_memory", {}) or {},
                "clarification_memory": snapshot_source.get("clarification_memory", {}) or {},
                "response_memory": snapshot_source.get("response_memory", {}) or {},
                "intent_memory": snapshot_source.get("intent_memory", {}) or {},
            }
        )

    if thread_id and not snapshot.thread_memory.thread_id:
        snapshot.thread_memory.thread_id = thread_id
    return snapshot


def apply_memory_update(snapshot: MemorySnapshot, update: MemoryUpdate) -> MemorySnapshot:
    next_snapshot = snapshot.model_copy(deep=True)
    next_snapshot = apply_thread_memory_update(next_snapshot, update)
    next_snapshot = apply_object_memory_update(next_snapshot, update)
    next_snapshot = apply_clarification_memory_update(next_snapshot, update)
    next_snapshot = apply_response_memory_update(next_snapshot, update)
    return next_snapshot


def serialize_memory_snapshot(snapshot: MemorySnapshot) -> dict[str, Any]:
    return snapshot.model_dump(mode="json")


def snapshot_to_route_state(
    snapshot: MemorySnapshot,
    *,
    route_phase: str = "active",
    last_assistant_prompt_type: str = "",
    session_payload: dict[str, Any] | None = None,
    extra_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_route_phase = route_phase or snapshot.thread_memory.route_phase or "active"
    effective_prompt_type = last_assistant_prompt_type or snapshot.thread_memory.last_assistant_prompt_type
    route_state = {
        "active_route": snapshot.thread_memory.active_route,
        "active_business_line": snapshot.thread_memory.active_business_line,
        "route_phase": effective_route_phase,
        "last_assistant_prompt_type": effective_prompt_type,
        "pending_route_after_clarification": snapshot.clarification_memory.pending_route_after_clarification,
        "pending_identifiers": (
            [snapshot.clarification_memory.pending_identifier]
            if snapshot.clarification_memory.pending_identifier
            else list(snapshot.clarification_memory.pending_candidate_options)
        ),
        "memory_snapshot": serialize_memory_snapshot(snapshot),
        "thread_memory": snapshot.thread_memory.model_dump(mode="json"),
        "object_memory": snapshot.object_memory.model_dump(mode="json"),
        "clarification_memory": snapshot.clarification_memory.model_dump(mode="json"),
        "response_memory": snapshot.response_memory.model_dump(mode="json"),
        "intent_memory": snapshot.intent_memory.model_dump(mode="json"),
        "session_payload": session_payload or {},
    }
    if extra_updates:
        route_state.update(extra_updates)
    return route_state
