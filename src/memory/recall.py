"""Memory Recall phase.

Runs at the beginning of each turn. Loads the prior snapshot, analyzes
the incoming query, and produces a MemoryContext that downstream modules consume.

Usage:
    from src.memory.recall import recall

    memory_context = recall(
        thread_id="thread-1",
        user_query="tell me more about the CAR-T construct",
        prior_state=prior_state_dict_or_snapshot,
    )
"""
from __future__ import annotations

import re
from typing import Any

from src.common.models import IntentGroup, ObjectRef
from src.memory.models import (
    BASE_WEIGHT_MAP,
    ConversationTrajectory,
    IntentDriftResult,
    MemoryContext,
    MemorySnapshot,
    ScoredObjectRef,
    compute_salience,
    salience_to_relevance,
)
from src.memory.store import load_memory_snapshot


# ---------------------------------------------------------------------------
# Follow-up phrases for drift detection (EN + ZH)
# ---------------------------------------------------------------------------

_FOLLOW_UP_PHRASES = [
    "tell me more", "more about", "continue", "go on",
    "also", "additionally", "what else", "can you elaborate",
    "about that", "regarding that", "the same",
    "再说说", "继续", "还有", "关于这个", "接着说", "多说一点",
]

_INFORMATIONAL_TOPICS = {
    "knowledge_lookup",
    "document_lookup",
    "commercial_or_operational_lookup",
    "general_support",
}

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "technical_question": ["mechanism", "protocol", "how does", "explain", "原理", "方案"],
    "pricing_question": ["price", "cost", "quote", "how much", "价格", "报价"],
    "order_support": ["order", "status", "tracking", "订单", "状态"],
    "product_inquiry": ["available", "offer", "product", "有没有", "产品"],
    "documentation_request": ["datasheet", "brochure", "coa", "sds", "文档"],
    "customization_request": ["custom", "tailor", "design", "定制"],
    "troubleshooting": ["problem", "issue", "failed", "not working", "问题", "故障"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recall(
    *,
    thread_id: str,
    user_query: str,
    prior_state: Any | None = None,
) -> MemoryContext:
    """Phase 1: Load and contextualize memory for the current turn."""

    # 1. Load snapshot
    snapshot = load_memory_snapshot(prior_state, thread_id=thread_id)

    # 2. Compute trajectory
    trajectory = _compute_trajectory(snapshot)

    # 3. Score object salience
    scored_objects = _score_recent_objects(snapshot)

    # 4. Detect intent drift
    prior_groups = list(snapshot.intent_memory.prior_intent_groups)
    drift = _detect_intent_drift(
        user_query=user_query,
        prior_groups=prior_groups,
        trajectory=trajectory,
    )

    # 5. Assemble MemoryContext
    return MemoryContext(
        snapshot=snapshot,
        prior_intent_groups=drift.resolved_groups,
        intent_continuity_confidence=drift.continuity_confidence,
        trajectory=trajectory,
        active_object=snapshot.object_memory.active_object,
        recent_objects_by_relevance=scored_objects,
        revealed_attributes=list(snapshot.response_memory.revealed_attributes),
        last_response_topics=list(snapshot.response_memory.last_response_topics),
        prior_demand_type=snapshot.response_memory.last_demand_type,
        prior_demand_flags=list(snapshot.response_memory.last_demand_flags),
    )


# ---------------------------------------------------------------------------
# Trajectory detection
# ---------------------------------------------------------------------------

def _compute_trajectory(snapshot: MemorySnapshot) -> ConversationTrajectory:
    thread = snapshot.thread_memory
    clarification = snapshot.clarification_memory
    objects = snapshot.object_memory
    response = snapshot.response_memory

    # Fresh start: no prior route or turn history
    if not thread.active_route and not thread.last_turn_type:
        return ConversationTrajectory(phase="fresh_start")

    # Clarification loop: we asked a question, waiting for answer
    if clarification.pending_clarification_type:
        return ConversationTrajectory(
            phase="clarification_loop",
            has_pending_clarification=True,
            prior_route=thread.active_route,
            prior_turn_type=thread.last_turn_type,
        )

    # Follow-up: last turn produced an informational response topic. Keep a
    # legacy fallback for older snapshots that still carry pre-v4 turn types.
    if (
        response.last_response_topics
        and response.last_response_topics[-1] in _INFORMATIONAL_TOPICS
    ) or thread.last_turn_type in {"answer", "clarification_answer"}:
        return ConversationTrajectory(
            phase="follow_up",
            prior_route=thread.active_route,
            prior_turn_type=thread.last_turn_type,
        )

    # Mid-topic: active object exists, conversation continues
    if objects.active_object:
        return ConversationTrajectory(
            phase="mid_topic",
            prior_route=thread.active_route,
            prior_turn_type=thread.last_turn_type,
        )

    # Default: topic switch or ambiguous
    return ConversationTrajectory(
        phase="topic_switch",
        prior_route=thread.active_route,
        prior_turn_type=thread.last_turn_type,
    )


# ---------------------------------------------------------------------------
# Object salience scoring
# ---------------------------------------------------------------------------

def _score_recent_objects(snapshot: MemorySnapshot) -> list[ScoredObjectRef]:
    """Compute salience for all recent objects. Sort by salience descending."""
    object_memory = snapshot.object_memory
    active_key = _object_ref_key(object_memory.active_object) if object_memory.active_object else None

    scored: list[ScoredObjectRef] = []
    for ref in object_memory.recent_objects:
        turn_age = ref.turn_age
        interaction_count = ref.interaction_count
        base_weight = BASE_WEIGHT_MAP.get(ref.object_type, 1.0)
        sal = compute_salience(base_weight, interaction_count, turn_age)
        is_active = _object_ref_key(ref) == active_key if active_key else False

        scored.append(ScoredObjectRef(
            object_ref=ref,
            turn_age=turn_age,
            interaction_count=interaction_count,
            base_weight=base_weight,
            is_active=is_active,
            salience=round(sal, 4),
            relevance=salience_to_relevance(sal),
        ))

    scored.sort(key=lambda s: s.salience, reverse=True)
    return scored


def _object_ref_key(ref: ObjectRef) -> tuple[str, str, str]:
    return (ref.object_type, ref.identifier, ref.display_name)

# ---------------------------------------------------------------------------
# Intent drift detection
# ---------------------------------------------------------------------------

def _detect_intent_drift(
    *,
    user_query: str,
    prior_groups: list[IntentGroup],
    trajectory: ConversationTrajectory,
) -> IntentDriftResult:
    """Detect whether the current query continues or drifts from prior intents."""

    if not prior_groups:
        return IntentDriftResult(
            continuity_confidence=0.0,
            drift_action="clear",
            resolved_groups=[],
            reason="no prior groups",
        )

    # Fresh start or topic switch: clear prior groups
    if trajectory.phase in {"fresh_start", "topic_switch"}:
        return IntentDriftResult(
            continuity_confidence=0.0,
            drift_action="clear",
            resolved_groups=[],
            reason=f"trajectory phase: {trajectory.phase}",
        )

    # Clarification loop: preserve prior groups fully
    if trajectory.phase == "clarification_loop":
        return IntentDriftResult(
            continuity_confidence=1.0,
            drift_action="preserve",
            resolved_groups=list(prior_groups),
            reason="clarification loop: groups unchanged",
        )

    # Follow-up or mid-topic: compute overlap score
    overlap = _compute_overlap_signals(user_query.lower(), prior_groups)

    if overlap.score >= 0.7:
        return IntentDriftResult(
            continuity_confidence=overlap.score,
            drift_action="preserve",
            resolved_groups=list(prior_groups),
            reason=f"high overlap: {overlap.matched_signals}",
        )
    elif overlap.score >= 0.3:
        return IntentDriftResult(
            continuity_confidence=overlap.score,
            drift_action="merge",
            resolved_groups=list(prior_groups),
            reason=f"moderate overlap: {overlap.matched_signals}",
        )
    elif overlap.score > 0:
        return IntentDriftResult(
            continuity_confidence=overlap.score,
            drift_action="stack",
            resolved_groups=[],
            reason=f"low overlap, stacking: {overlap.matched_signals}",
        )
    else:
        return IntentDriftResult(
            continuity_confidence=0.0,
            drift_action="clear",
            resolved_groups=[],
            reason="no overlap with prior groups",
        )


class _OverlapSignals:
    __slots__ = ("score", "matched_signals")

    def __init__(self) -> None:
        self.score: float = 0.0
        self.matched_signals: list[str] = []


def _compute_overlap_signals(
    query_lower: str,
    prior_groups: list[IntentGroup],
) -> _OverlapSignals:
    """Compute semantic overlap between current query and prior IntentGroups."""
    result = _OverlapSignals()

    # 1. Entity name overlap (strongest signal)
    for group in prior_groups:
        name = (group.object_display_name or group.object_identifier or "").lower()
        if name and name in query_lower:
            result.matched_signals.append(f"entity_match:{name}")
            result.score += 0.4

    # 2. Follow-up language (moderate signal)
    if any(phrase in query_lower for phrase in _FOLLOW_UP_PHRASES):
        result.matched_signals.append("follow_up_language")
        result.score += 0.3

    # 3. Intent keyword overlap (weak signal)
    prior_intents = {g.intent for g in prior_groups}
    for intent in prior_intents:
        keywords = _INTENT_KEYWORDS.get(intent, [])
        if any(kw in query_lower for kw in keywords):
            result.matched_signals.append(f"intent_keyword:{intent}")
            result.score += 0.15

    # 4. New entity detection (negative signal — drift indicator)
    prior_entities = set()
    for g in prior_groups:
        if g.object_identifier:
            prior_entities.add(g.object_identifier.lower())
        if g.object_display_name:
            prior_entities.add(g.object_display_name.lower())

    new_identifiers = re.findall(r"\b(?:pm-)?[a-z]*\d{4,}\b", query_lower)
    for nid in new_identifiers:
        if nid not in prior_entities:
            result.matched_signals.append(f"new_entity:{nid}")
            result.score -= 0.3

    result.score = max(0.0, min(1.0, result.score))
    return result
