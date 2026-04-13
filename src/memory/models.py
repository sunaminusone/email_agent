from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import IntentGroup, ObjectRef, ObjectType, ValueSignal


class _MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Sub-memory domains
# ---------------------------------------------------------------------------

class ThreadMemory(_MemoryModel):
    thread_id: str | None = None
    active_route: str = ""
    continuity_mode: str = ""
    last_turn_type: str = ""
    route_phase: str = ""
    last_assistant_prompt_type: str = ""
    last_user_goal: str = ""
    active_business_line: str = ""


class ObjectMemory(_MemoryModel):
    active_object: ObjectRef | None = None
    secondary_active_objects: list[ObjectRef] = Field(default_factory=list)
    recent_objects: list[ObjectRef] = Field(default_factory=list)
    candidate_object_sets: list[dict[str, Any]] = Field(default_factory=list)


class ClarificationMemory(_MemoryModel):
    pending_clarification_type: str = ""
    pending_candidate_options: list[str] = Field(default_factory=list)
    pending_identifier: str = ""
    pending_question: str = ""
    pending_route_after_clarification: str = ""


class ResponseMemory(_MemoryModel):
    revealed_attributes: list[str] = Field(default_factory=list)
    last_tool_results: list[dict[str, Any]] = Field(default_factory=list)
    last_response_topics: list[str] = Field(default_factory=list)
    last_demand_type: str = "general"
    last_demand_flags: list[str] = Field(default_factory=list)


class IntentMemory(_MemoryModel):
    """Tracks intent groups across turns with drift detection."""
    prior_intent_groups: list[IntentGroup] = Field(default_factory=list)
    stacked_intent_history: list[list[IntentGroup]] = Field(default_factory=list)
    prior_primary_intent: str = "unknown"
    continuity_confidence: float = 0.0
    turns_since_last_intent_change: int = 0


# ---------------------------------------------------------------------------
# Stateful anchors (read-only view for downstream)
# ---------------------------------------------------------------------------

class StatefulAnchors(_MemoryModel):
    active_route: str = ""
    pending_clarification_field: str = ""
    pending_candidate_options: list[str] = Field(default_factory=list)
    pending_identifier: str = ""


# ---------------------------------------------------------------------------
# Snapshot and update
# ---------------------------------------------------------------------------

class MemorySnapshot(_MemoryModel):
    """Canonical typed state. Single source of truth."""
    thread_memory: ThreadMemory = Field(default_factory=ThreadMemory)
    object_memory: ObjectMemory = Field(default_factory=ObjectMemory)
    clarification_memory: ClarificationMemory = Field(default_factory=ClarificationMemory)
    response_memory: ResponseMemory = Field(default_factory=ResponseMemory)
    intent_memory: IntentMemory = Field(default_factory=IntentMemory)


class MemoryUpdate(_MemoryModel):
    thread_memory: ThreadMemory | None = None
    set_active_object: ObjectRef | None = None
    secondary_active_objects: list[ObjectRef] = Field(default_factory=list)
    append_recent_objects: list[ObjectRef] = Field(default_factory=list)
    candidate_object_sets: list[dict[str, Any]] = Field(default_factory=list)
    set_pending_clarification: ClarificationMemory | None = None
    clear_pending_clarification: bool = False
    mark_revealed_attributes: list[str] = Field(default_factory=list)
    set_last_tool_results: list[dict[str, Any]] = Field(default_factory=list)
    set_last_response_topics: list[str] = Field(default_factory=list)
    set_last_demand_type: str | None = None
    set_last_demand_flags: list[str] = Field(default_factory=list)
    response_memory: ResponseMemory | None = None
    route_updates: dict[str, Any] = Field(default_factory=dict)
    soft_reset_current_topic: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Salience scoring
# ---------------------------------------------------------------------------

BASE_WEIGHT_MAP: dict[str, float] = {
    "scientific_target": 2.5,
    "service": 2.0,
    "product": 1.5,
    "order": 1.5,
    "invoice": 1.0,
    "shipment": 1.0,
    "document": 1.0,
    "customer": 1.0,
    "unknown": 1.0,
}

SALIENCE_HIGH = 2.0
SALIENCE_MEDIUM = 0.5
SALIENCE_EVICTION = 0.3


def compute_salience(base_weight: float, interaction_count: int, turn_age: int) -> float:
    return (base_weight * interaction_count) / max(turn_age, 1)


def salience_to_relevance(salience: float) -> Literal["high", "medium", "low"]:
    if salience >= SALIENCE_HIGH:
        return "high"
    if salience >= SALIENCE_MEDIUM:
        return "medium"
    return "low"


class ScoredObjectRef(_MemoryModel):
    """ObjectRef with salience scoring for prioritized surfacing."""
    object_ref: ObjectRef
    turn_age: int = 0
    interaction_count: int = 1
    base_weight: float = 1.0
    is_active: bool = False
    salience: float = 1.0
    relevance: Literal["high", "medium", "low"] = "low"


# ---------------------------------------------------------------------------
# Conversation trajectory
# ---------------------------------------------------------------------------

TrajectoryPhase = Literal[
    "fresh_start",
    "mid_topic",
    "clarification_loop",
    "follow_up",
    "topic_switch",
]


class ConversationTrajectory(_MemoryModel):
    """Where are we in the conversation flow?"""
    phase: TrajectoryPhase = "fresh_start"
    turns_on_current_topic: int = 0
    has_pending_clarification: bool = False
    prior_route: str = ""
    prior_turn_type: str = ""


# ---------------------------------------------------------------------------
# Intent drift
# ---------------------------------------------------------------------------

DriftAction = Literal["preserve", "merge", "stack", "clear"]


class IntentDriftResult(_MemoryModel):
    """Result of intent drift detection."""
    continuity_confidence: float = 0.0
    drift_action: DriftAction = "clear"
    resolved_groups: list[IntentGroup] = Field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# MemoryContext (produced by recall, consumed by all downstream modules)
# ---------------------------------------------------------------------------

class MemoryContext(_MemoryModel):
    """Enriched, prioritized memory view for the current turn."""
    snapshot: MemorySnapshot = Field(default_factory=MemorySnapshot)
    stateful_anchors: StatefulAnchors = Field(default_factory=StatefulAnchors)
    prior_intent_groups: list[IntentGroup] = Field(default_factory=list)
    intent_continuity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    trajectory: ConversationTrajectory = Field(default_factory=ConversationTrajectory)
    active_object: ObjectRef | None = None
    recent_objects_by_relevance: list[ScoredObjectRef] = Field(default_factory=list)
    revealed_attributes: list[str] = Field(default_factory=list)
    last_response_topics: list[str] = Field(default_factory=list)
    prior_demand_type: str = "general"
    prior_demand_flags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# MemoryContribution (emitted by each pipeline layer, merged by reflect)
# ---------------------------------------------------------------------------

class MemoryContribution(_MemoryModel):
    """Partial memory update from one pipeline layer."""
    source: Literal["ingestion", "objects", "routing", "executor", "response"]

    # Thread state (typically from routing)
    active_route: str | None = None
    route_phase: str | None = None
    active_business_line: str | None = None

    # Object state (typically from objects layer)
    set_active_object: ObjectRef | None = None
    secondary_active_objects: list[ObjectRef] | None = None
    append_recent_objects: list[ObjectRef] | None = None

    # Clarification state (typically from routing)
    set_pending_clarification: ClarificationMemory | None = None
    clear_pending_clarification: bool = False

    # Response state (typically from response layer)
    mark_revealed_attributes: list[str] | None = None
    set_last_tool_results: list[dict[str, Any]] | None = None
    set_last_response_topics: list[str] | None = None
    set_last_demand_type: str | None = None
    set_last_demand_flags: list[str] | None = None

    # Intent groups (typically from assembly step)
    intent_groups: list[IntentGroup] | None = None

    # Control signals
    soft_reset_current_topic: bool = False
    reason: str = ""
