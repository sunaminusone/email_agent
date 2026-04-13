"""Memory Reflect phase.

Runs at the end of each turn. Collects MemoryContribution objects from each
pipeline layer, merges them, applies salience decay, stores IntentGroups with
drift-aware stack/clear, and produces the next MemorySnapshot.

Usage:
    from src.memory.reflect import reflect

    next_snapshot = reflect(
        current_snapshot=memory_context.snapshot,
        contributions=[objects_contrib, routing_contrib, response_contrib],
        thread_id="thread-1",
        normalized_query="check order 12345",
        last_turn_type="answer",
    )
"""
from __future__ import annotations

from typing import Any

from src.common.models import IntentGroup, ObjectRef
from src.memory.models import (
    BASE_WEIGHT_MAP,
    SALIENCE_EVICTION,
    ClarificationMemory,
    IntentMemory,
    MemoryContribution,
    MemorySnapshot,
    MemoryUpdate,
    ThreadMemory,
    compute_salience,
)
from src.memory.store import apply_memory_update


MAX_RECENT_OBJECTS = 15
MAX_STACKED_HISTORY_DEPTH = 3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reflect(
    *,
    current_snapshot: MemorySnapshot,
    contributions: list[MemoryContribution],
    thread_id: str,
    normalized_query: str = "",
    last_turn_type: str = "",
) -> MemorySnapshot:
    """Phase 2: Merge contributions and produce the next snapshot."""

    # 1. Merge contributions into a single MemoryUpdate
    update = _merge_contributions(contributions, thread_id, normalized_query, last_turn_type)

    # 2. Apply update to current snapshot
    next_snapshot = apply_memory_update(current_snapshot, update)

    # 3. Apply salience decay
    next_snapshot = _apply_salience_decay(next_snapshot)

    # 4. Store intent groups with drift-aware logic
    next_snapshot = _store_intent_groups(next_snapshot, contributions)

    return next_snapshot


# ---------------------------------------------------------------------------
# Contribution merging
# ---------------------------------------------------------------------------

def _merge_contributions(
    contributions: list[MemoryContribution],
    thread_id: str,
    normalized_query: str,
    last_turn_type: str,
) -> MemoryUpdate:
    """Merge all layer contributions into one MemoryUpdate.

    Merge rules:
    - Scalar fields (active_route, route_phase): last writer wins
    - List fields (append_recent_objects): concatenate + dedupe
    - Control signals (soft_reset): any True wins (OR semantics)
    """
    update = MemoryUpdate()

    # Build thread memory from contributions
    active_route = ""
    route_phase = "active"
    active_business_line = ""
    for c in contributions:
        if c.active_route is not None:
            active_route = c.active_route
        if c.route_phase is not None:
            route_phase = c.route_phase
        if c.active_business_line is not None:
            active_business_line = c.active_business_line

    update.thread_memory = ThreadMemory(
        thread_id=thread_id,
        active_route=active_route,
        route_phase=route_phase,
        last_turn_type=last_turn_type,
        last_user_goal=normalized_query,
        active_business_line=active_business_line,
    )

    # Merge object contributions
    all_recent: list[ObjectRef] = []
    for c in contributions:
        if c.set_active_object is not None:
            update.set_active_object = c.set_active_object
        if c.secondary_active_objects is not None:
            update.secondary_active_objects = list(c.secondary_active_objects)
        if c.append_recent_objects is not None:
            all_recent.extend(c.append_recent_objects)
    if all_recent:
        update.append_recent_objects = all_recent

    # Merge clarification
    for c in contributions:
        if c.clear_pending_clarification or c.soft_reset_current_topic:
            update.clear_pending_clarification = True
        if c.set_pending_clarification is not None:
            update.set_pending_clarification = c.set_pending_clarification

    # Merge response state
    all_revealed: list[str] = []
    all_topics: list[str] = []
    for c in contributions:
        if c.mark_revealed_attributes is not None:
            all_revealed.extend(c.mark_revealed_attributes)
        if c.set_last_tool_results is not None:
            update.set_last_tool_results = list(c.set_last_tool_results)
        if c.set_last_response_topics is not None:
            all_topics.extend(c.set_last_response_topics)
    if all_revealed:
        update.mark_revealed_attributes = all_revealed
    if all_topics:
        update.set_last_response_topics = all_topics

    # Demand state (from response layer)
    for c in contributions:
        if c.set_last_demand_type is not None:
            update.set_last_demand_type = c.set_last_demand_type
        if c.set_last_demand_flags is not None:
            update.set_last_demand_flags = list(c.set_last_demand_flags)

    # Soft reset: any True wins
    if any(c.soft_reset_current_topic for c in contributions):
        update.soft_reset_current_topic = True

    # Merge reason
    reasons = [c.reason for c in contributions if c.reason]
    update.reason = "; ".join(reasons) if reasons else ""

    return update


# ---------------------------------------------------------------------------
# Salience decay
# ---------------------------------------------------------------------------

def _apply_salience_decay(snapshot: MemorySnapshot) -> MemorySnapshot:
    """Increment turn_age, update interaction_count for re-referenced objects,
    evict objects below salience threshold."""
    objects = snapshot.object_memory

    # Identify objects referenced this turn (active + secondary)
    referenced_keys: set[tuple[str, str, str]] = set()
    if objects.active_object:
        referenced_keys.add(_object_key(objects.active_object))
    for ref in objects.secondary_active_objects:
        referenced_keys.add(_object_key(ref))

    surviving: list[ObjectRef] = []
    for ref in objects.recent_objects:
        key = _object_key(ref)

        new_age = ref.turn_age + 1
        new_count = ref.interaction_count
        if key in referenced_keys:
            new_count += 1
            new_age = 1  # reset age when re-referenced

        base_weight = BASE_WEIGHT_MAP.get(ref.object_type, 1.0)
        sal = compute_salience(base_weight, new_count, new_age)

        if sal >= SALIENCE_EVICTION:
            surviving.append(ref.model_copy(update={
                "turn_age": new_age,
                "interaction_count": new_count,
            }))

    # Hard cap: keep top by salience
    if len(surviving) > MAX_RECENT_OBJECTS:
        surviving.sort(
            key=lambda r: compute_salience(
                BASE_WEIGHT_MAP.get(r.object_type, 1.0),
                r.interaction_count,
                r.turn_age,
            ),
            reverse=True,
        )
        surviving = surviving[:MAX_RECENT_OBJECTS]

    return snapshot.model_copy(deep=True, update={
        "object_memory": snapshot.object_memory.model_copy(update={
            "recent_objects": surviving,
        })
    })


def _object_key(ref: ObjectRef) -> tuple[str, str, str]:
    return (ref.object_type, ref.identifier, ref.display_name)


# ---------------------------------------------------------------------------
# Intent group storage with drift-aware stack/clear
# ---------------------------------------------------------------------------

def _store_intent_groups(
    snapshot: MemorySnapshot,
    contributions: list[MemoryContribution],
) -> MemorySnapshot:
    """Store this turn's IntentGroups in IntentMemory.

    Drift-aware logic:
    - If soft_reset: clear all groups and stack
    - If new groups provided: replace prior_intent_groups, push old ones to stack
    - If no groups: increment turns_since_last_intent_change
    """
    current_intent_memory = snapshot.intent_memory
    soft_reset = any(c.soft_reset_current_topic for c in contributions)

    # Collect intent groups from contributions
    new_groups: list[IntentGroup] = []
    for c in contributions:
        if c.intent_groups is not None:
            new_groups = list(c.intent_groups)
            break  # only one contribution should provide intent groups

    if soft_reset:
        # Full reset: clear groups, clear stack
        return snapshot.model_copy(deep=True, update={
            "intent_memory": IntentMemory(),
        })

    if new_groups:
        # Determine primary intent from new groups
        new_primary = new_groups[0].intent if new_groups else "unknown"
        old_groups = list(current_intent_memory.prior_intent_groups)

        # Check if intents actually changed
        old_intents = {g.intent for g in old_groups}
        new_intents = {g.intent for g in new_groups}
        intents_changed = old_intents != new_intents

        # Build updated stack
        stacked = list(current_intent_memory.stacked_intent_history)
        if old_groups and intents_changed:
            stacked.append(old_groups)
            stacked = stacked[-MAX_STACKED_HISTORY_DEPTH:]

        return snapshot.model_copy(deep=True, update={
            "intent_memory": IntentMemory(
                prior_intent_groups=new_groups,
                stacked_intent_history=stacked,
                prior_primary_intent=new_primary,
                continuity_confidence=current_intent_memory.continuity_confidence,
                turns_since_last_intent_change=0 if intents_changed else current_intent_memory.turns_since_last_intent_change,
            ),
        })

    # No new groups: increment turn counter
    return snapshot.model_copy(deep=True, update={
        "intent_memory": current_intent_memory.model_copy(update={
            "turns_since_last_intent_change": current_intent_memory.turns_since_last_intent_change + 1,
        }),
    })
