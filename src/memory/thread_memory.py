from __future__ import annotations

from src.memory.models import MemorySnapshot, MemoryUpdate


def apply_thread_memory_update(snapshot: MemorySnapshot, update: MemoryUpdate) -> MemorySnapshot:
    next_snapshot = snapshot.model_copy(deep=True)
    if "thread_memory" in update.model_fields_set and update.thread_memory is not None:
        next_snapshot.thread_memory = update.thread_memory.model_copy(deep=True)
    return next_snapshot
