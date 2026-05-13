from __future__ import annotations

from typing import Any

from src.memory.clarification_memory import apply_clarification_memory_update
from src.memory.models import (
    ClarificationMemory,
    IntentMemory,
    MemorySnapshot,
    MemoryUpdate,
    ObjectMemory,
    ResponseMemory,
    ThreadMemory,
)
from src.memory.object_memory import apply_object_memory_update
from src.memory.response_memory import apply_response_memory_update
from src.memory.thread_memory import apply_thread_memory_update


def _filter_model_fields(payload: Any, model_cls: type) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    allowed = set(model_cls.model_fields)
    return {key: value for key, value in payload.items() if key in allowed}


def load_memory_snapshot(prior_state: Any | None = None, *, thread_id: str | None = None) -> MemorySnapshot:
    if isinstance(prior_state, MemorySnapshot):
        snapshot = prior_state.model_copy(deep=True)
    else:
        source = prior_state if isinstance(prior_state, dict) else {}
        snapshot_source = source.get("memory_snapshot", source) if isinstance(source.get("memory_snapshot"), dict) else source
        snapshot = MemorySnapshot.model_validate(
            {
                "thread_memory": _filter_model_fields(snapshot_source.get("thread_memory", {}) or {}, ThreadMemory),
                "object_memory": _filter_model_fields(snapshot_source.get("object_memory", {}) or {}, ObjectMemory),
                "clarification_memory": _filter_model_fields(
                    snapshot_source.get("clarification_memory", {}) or {}, ClarificationMemory
                ),
                "response_memory": _filter_model_fields(snapshot_source.get("response_memory", {}) or {}, ResponseMemory),
                "intent_memory": _filter_model_fields(snapshot_source.get("intent_memory", {}) or {}, IntentMemory),
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
