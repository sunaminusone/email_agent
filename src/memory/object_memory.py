from __future__ import annotations

from src.common.models import ObjectRef
from src.memory.models import MemorySnapshot, MemoryUpdate


def apply_object_memory_update(snapshot: MemorySnapshot, update: MemoryUpdate) -> MemorySnapshot:
    next_snapshot = snapshot.model_copy(deep=True)
    explicit_fields = update.model_fields_set

    if "set_active_object" in explicit_fields:
        next_snapshot.object_memory.active_object = (
            update.set_active_object.model_copy(deep=True)
            if update.set_active_object is not None
            else None
        )

    if "secondary_active_objects" in explicit_fields:
        next_snapshot.object_memory.secondary_active_objects = [
            item.model_copy(deep=True) for item in update.secondary_active_objects
        ]

    if "append_recent_objects" in explicit_fields:
        merged_recent = [
            *next_snapshot.object_memory.recent_objects,
            *[item.model_copy(deep=True) for item in update.append_recent_objects],
        ]
        next_snapshot.object_memory.recent_objects = dedupe_object_refs(merged_recent)[-15:]

    if "candidate_object_sets" in explicit_fields:
        next_snapshot.object_memory.candidate_object_sets = [dict(item) for item in update.candidate_object_sets]

    if update.soft_reset_current_topic:
        next_snapshot.object_memory.active_object = None
        next_snapshot.object_memory.secondary_active_objects = []
        next_snapshot.object_memory.candidate_object_sets = []

    return next_snapshot


def dedupe_object_refs(objects: list[ObjectRef]) -> list[ObjectRef]:
    """Dedupe by (object_type, identifier, display_name, business_line).

    When a duplicate is found, keep the entry with higher interaction_count
    (merge counts and take the lower turn_age).
    """
    best: dict[tuple[str, str, str, str], ObjectRef] = {}

    for obj in objects:
        signature = (
            obj.object_type,
            obj.identifier,
            obj.display_name,
            obj.business_line,
        )
        existing = best.get(signature)
        if existing is None:
            best[signature] = obj
        else:
            # Merge: take higher interaction_count, lower turn_age
            merged_count = max(existing.interaction_count, obj.interaction_count)
            merged_age = min(existing.turn_age, obj.turn_age)
            best[signature] = existing.model_copy(update={
                "interaction_count": merged_count,
                "turn_age": merged_age,
            })

    return list(best.values())
