from __future__ import annotations

from src.memory.models import ClarificationMemory, MemorySnapshot, MemoryUpdate


def apply_clarification_memory_update(snapshot: MemorySnapshot, update: MemoryUpdate) -> MemorySnapshot:
    next_snapshot = snapshot.model_copy(deep=True)

    if update.soft_reset_current_topic or update.clear_pending_clarification:
        next_snapshot.clarification_memory = ClarificationMemory()

    if "set_pending_clarification" in update.model_fields_set:
        next_snapshot.clarification_memory = (
            update.set_pending_clarification.model_copy(deep=True)
            if update.set_pending_clarification is not None
            else ClarificationMemory()
        )

    return next_snapshot
