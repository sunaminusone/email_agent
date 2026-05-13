# Memory Design v4

## Purpose

The memory module preserves typed state across conversation turns and
actively surfaces relevant context for each new turn. It is the only
module that spans the entire pipeline — reading at turn start, writing at
turn end.

**v4 framing**: memory is reused unchanged from v3. Multi-turn state is
just as important in v4 — the rep may iteratively refine a draft with the
agent, ask follow-up questions about a specific past customer, or triage
multiple inquiries in the same session. The two-phase recall/reflect
design carries over wholesale.

In v3 (and still in v4), memory evolves from a **passive data store** to
an **active participant** in the agent loop. Instead of dumping a raw
snapshot into the pipeline and collecting all outputs at the end, memory
operates in two explicit phases:

> **Recall**: At turn start, analyze the incoming query against stored state and produce a prioritized, enriched context for downstream modules.
>
> **Reflect**: At turn end, analyze what happened during the turn and selectively decide what to remember, update, or discard.

This is the "agent-like" behavior — memory has perception (what's relevant?), reasoning (should I surface this? is this stale?), and action (what to keep, what to forget).

### What changes in v3

1. **Two-phase memory lifecycle** — explicit `recall()` and `reflect()` entry points replace ad-hoc load/build-update patterns
2. **MemoryContext is the single downstream input** — replaces both raw snapshot reads and the previous StatefulAnchors wrapper. Prioritized fields (active_object, scored recent objects, trajectory, prior IntentGroups) are surfaced directly; the original `MemorySnapshot` is exposed via `MemoryContext.snapshot` for modules that need raw sub-memory access (`thread_memory`, `clarification_memory`, etc.). The `StatefulAnchors` wrapper has been removed.
3. **IntentGroup continuity** — prior turn's `list[IntentGroup]` stored in memory, enabling multi-turn follow-up ("tell me more about the second thing")
4. **Distributed memory update** — each layer can emit a partial `MemoryContribution`, the Reflect phase merges them instead of one giant `_build_memory_update()` in service.py
5. **Object salience scoring** — recent objects carry `turn_age`, `interaction_count`, and `base_weight`; salience formula determines whether they're surfaced as active context or just retained as history. High-interaction foundational objects (e.g., a specific protein ID) survive long gaps without mention
6. **Intent drift detection** — IntentMemory tracks `continuity_confidence`; when semantic drift exceeds a threshold, prior IntentGroups are cleared or stacked to prevent the agent from hallucinating continuity with a stale topic
7. **route_state as computed view** — `MemorySnapshot` is the single source of truth; `route_state` is derived on demand, not separately persisted

### What does NOT change

- `MemorySnapshot` as the canonical typed state object
- `MemoryUpdate` as the declarative patch mechanism (explicit field tracking via `model_fields_set`)
- Sub-memory domain structure: Thread, Object, Clarification, Response
- Redis-backed persistence via `SessionStore` + `RedisSessionAdapter`
- Immutability pattern (deep copy on update, no live mutation)
- Soft reset semantics (clear active context, preserve history)
- `ObjectRef` as the lightweight entity pointer in memory

## Current State Analysis

### What exists (`src/memory/`)

| File | Role | v3 status |
| --- | --- | --- |
| `models.py` | MemorySnapshot, MemoryUpdate, sub-memories, MemoryContext, IntentMemory | **Extend** — added IntentMemory, object turn_age, MemoryContext; **removed** StatefulAnchors wrapper |
| `store.py` | load / apply / serialize / snapshot_to_route_state | **Refactor** — recall/reflect entry points |
| `session_store.py` | Redis-backed session management | Unchanged |
| `adapters/redis_store.py` | Redis adapter | Unchanged |
| `thread_memory.py` | Thread-level state updates | Unchanged |
| `object_memory.py` | Object-level state updates | **Minor** — add turn_age decay |
| `clarification_memory.py` | Pending clarification state | Unchanged |
| `response_memory.py` | Response history state | Unchanged |
| `view.py` | Extraction helpers (SimpleNamespace views) | **Deprecate** — replaced by MemoryContext |

### Related files in other modules

| File | Memory role | v3 status |
| --- | --- | --- |
| `ingestion/stateful_anchors.py` | (v2/v3) Extracts StatefulAnchors from prior state | **Removed** — downstream now reads prior state directly via `IngestionBundle.thread_memory` / `clarification_memory` (proxies onto `MemoryContext.snapshot`) |
| `app/service.py: _build_memory_update()` | Builds MemoryUpdate from all layer outputs | **Replace with reflect()** |
| `response/planner.py: _build_memory_update()` | Response-layer memory contribution | **Emit MemoryContribution instead** |

### What works well

1. **Immutable snapshots** — `model_copy(deep=True)` ensures safe concurrent access. Each turn gets a frozen snapshot at start, produces a new snapshot at end. No mid-turn mutations.

2. **Explicit field tracking** — `MemoryUpdate` uses `model_fields_set` to distinguish "explicitly set to None" from "not mentioned". Prevents accidental resets of fields the updater didn't intend to touch.

3. **Domain decomposition** — Thread, Object, Clarification, Response are independent sub-memories with isolated update logic. Adding a new sub-memory doesn't break existing ones.

4. **Soft reset semantics** — `soft_reset_current_topic` clears active context (object, clarification) while preserving history (recent_objects, response_topics). Enables clean topic transitions.

### What's insufficient for v3

1. **Memory was passive.** In v2/v3, `load_memory_snapshot()` returned a raw snapshot and downstream modules either read sub-memories directly or went through a `StatefulAnchors` wrapper that mechanically copied fields. Neither analyzed whether memory content was relevant to the current query or whether it was stale.

2. **No IntentGroup continuity.** The ingestion v3 design identified "multi-turn group continuity" as a known gap. Memory doesn't store prior IntentGroups, so "tell me more about the second thing" loses the group structure from the prior turn.

3. **`_build_memory_update()` is monolithic.** In `service.py`, a single function (~80 lines) synthesizes a MemoryUpdate from ingestion + objects + routing + response outputs. This couples the orchestrator to every module's internals.

4. **Dual persistence is fragile.** Both `memory_snapshot` and `route_state` are persisted to Redis. They can diverge if only one is updated. `route_state` should be a computed view of `MemorySnapshot`, not a separately maintained copy.

5. **No object salience.** `recent_objects` keeps the last 10 objects by insertion order. An object mentioned once 8 turns ago has the same status as one discussed last turn. In biotech conversations, foundational objects (a specific protein ID, a cell line, a construct) may not be mentioned every turn but remain the keystone of the entire discussion. Simple turn-age eviction would prematurely discard them.

6. **No intent drift detection.** IntentMemory stores prior IntentGroups but has no mechanism to detect when the user's new query has semantically drifted away from those groups. Without drift detection, the agent may hallucinate continuity with a stale topic ("tell me more" + tangential new content gets misrouted to the prior topic's tools).

6. **View helpers return untyped SimpleNamespace.** `active_entity_from_memory_snapshot()` returns a `SimpleNamespace` instead of a typed model. This weakens the contract between memory and downstream modules.

## v3 Design

### Overview: Recall / Reflect lifecycle

```
                        ┌─────────────────────────────────┐
                        │          Memory Module           │
                        │                                  │
   User query ─────────▶│  RECALL                          │
   Prior snapshot ──────▶│    load_snapshot()               │
                        │    analyze_relevance(query)      │
                        │    surface_context()             │
                        │           │                      │
                        │           ▼                      │
                        │    MemoryContext                  │──────▶ Pipeline
                        │                                  │         (Ingestion,
                        │                                  │          Objects,
                        │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │          Routing,
                        │                                  │          Executor,
   MemoryContributions ─▶│  REFLECT                         │          Response)
   (from each layer)    │    merge_contributions()         │
                        │    apply_decay()                 │
                        │    build_next_snapshot()         │
                        │           │                      │
                        │           ▼                      │
                        │    MemorySnapshot (next)         │──────▶ Persist
                        └─────────────────────────────────┘
```

### Phase 1: Recall

Recall runs at the beginning of each turn. It loads the prior snapshot, analyzes the incoming query, and produces a `MemoryContext` that downstream modules consume.

#### What Recall does

1. **Load snapshot** — rehydrate `MemorySnapshot` from Redis session or prior state dict
2. **Compute conversation trajectory** — what phase are we in? (fresh start / mid-topic / clarification loop / follow-up chain / topic switch)
3. **Score object salience** — compute `salience = (base_weight × interaction_count) / max(turn_age, 1)` for all recent objects, classify into high/medium/low relevance
4. **Detect intent drift** — compare current query signals against prior IntentGroups; if drift exceeds threshold, downgrade `continuity_confidence`
5. **Produce MemoryContext** — a typed, prioritized view that exposes prioritized fields directly (`active_object`, `recent_objects_by_relevance`, `trajectory`, `prior_intent_groups`, response/demand history) and makes the raw `MemorySnapshot` available via `MemoryContext.snapshot` for modules that need direct sub-memory access (`thread_memory`, `clarification_memory`)

#### MemoryContext contract

```python
class MemoryContext(BaseModel):
    """Enriched, prioritized memory view for the current turn.
    Produced by recall(), consumed by all downstream modules."""
    model_config = ConfigDict(extra="forbid")

    # Snapshot reference. Downstream modules read prior-state sub-memories
    # directly off `snapshot.thread_memory` / `snapshot.clarification_memory`
    # (typically via `IngestionBundle.thread_memory` / `clarification_memory`
    # property accessors). Replaces the legacy `StatefulAnchors` wrapper.
    snapshot: MemorySnapshot

    # Prior turn's IntentGroups (for assembly continuity)
    # Filtered by intent drift detection: stale groups are removed before surfacing
    prior_intent_groups: list[IntentGroup] = Field(default_factory=list)

    # How confident we are that prior_intent_groups still apply to the current turn
    # 1.0 = strong continuity (follow-up on same topic)
    # 0.5 = moderate (some overlap but new elements)
    # 0.0 = no continuity (topic switch, groups were cleared)
    intent_continuity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Conversation trajectory
    trajectory: ConversationTrajectory

    # Object context (relevance-scored)
    active_object: ObjectRef | None = None
    recent_objects_by_relevance: list[ScoredObjectRef] = Field(default_factory=list)

    # Response context (for repetition avoidance)
    revealed_attributes: list[str] = Field(default_factory=list)
    last_response_topics: list[str] = Field(default_factory=list)

    # Demand-profile continuity (carried across turns for stable routing)
    prior_demand_type: str = "general"
    prior_demand_flags: list[str] = Field(default_factory=list)
```

```python
class ConversationTrajectory(BaseModel):
    """Where are we in the conversation flow?"""
    model_config = ConfigDict(extra="forbid")

    phase: Literal[
        "fresh_start",          # no prior state, first message in thread
        "mid_topic",            # continuing discussion of an active object/topic
        "clarification_loop",   # waiting for user to answer a clarification question
        "follow_up",            # user is following up on a prior turn's result
        "topic_switch",         # user changed topic (different object or intent)
    ] = "fresh_start"
    turns_on_current_topic: int = 0
    has_pending_clarification: bool = False
    prior_route: str = ""
    prior_turn_type: str = ""
```

```python
class ScoredObjectRef(BaseModel):
    """ObjectRef with salience scoring.
    
    Salience formula:
        salience = (base_weight × interaction_count) / max(turn_age, 1)
    
    A protein ID mentioned in 5 turns (interaction_count=5, base_weight=2.0)
    retains salience=10.0 even after 3 turns of silence (turn_age=3 → 3.33).
    A generic product mentioned once (interaction_count=1, base_weight=1.0)
    drops to salience=0.25 after 4 turns (turn_age=4 → 0.25).
    """
    model_config = ConfigDict(extra="forbid")

    object_ref: ObjectRef
    turn_age: int = 0               # turns since last referenced
    interaction_count: int = 1      # how many turns have referenced this object
    base_weight: float = 1.0        # domain importance (see BASE_WEIGHT_MAP)
    is_active: bool = False         # is this the current active object?
    salience: float = 1.0           # computed: (base_weight × interaction_count) / max(turn_age, 1)
    relevance: Literal["high", "medium", "low"] = "low"  # derived from salience thresholds
```

**Base weight by object type** — biotech domain objects that typically serve as conversation keystones get higher base weights:

```python
BASE_WEIGHT_MAP: dict[str, float] = {
    # Foundational: these are often the "anchor" of an entire conversation
    "scientific_target": 2.5,   # protein ID, gene target, receptor
    "service": 2.0,             # custom service project (long-running context)

    # Standard: frequently referenced but more transient
    "product": 1.5,             # catalog product
    "order": 1.5,               # order number

    # Operational: typically one-shot lookups
    "invoice": 1.0,
    "shipment": 1.0,
    "document": 1.0,
    "customer": 1.0,
}
```

**Salience thresholds**:

| Salience range | Relevance | Behavior |
| --- | --- | --- |
| ≥ 2.0 | `high` | Surfaced in MemoryContext, available for reference resolution |
| 0.5 – 2.0 | `medium` | Retained in memory, available if explicitly referenced |
| < 0.5 | `low` | Candidate for eviction at next reflect cycle |

#### Recall implementation sketch

```python
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

    # 4. Detect intent drift and resolve prior IntentGroups
    prior_groups = list(snapshot.intent_memory.prior_intent_groups)
    drift = _detect_intent_drift(
        user_query=user_query,
        prior_groups=prior_groups,
        trajectory=trajectory,
    )

    # 5. Assemble MemoryContext. Prior-state fields that older designs wrapped
    # in StatefulAnchors are now reached via snapshot sub-memories
    # (snapshot.thread_memory.active_route, snapshot.clarification_memory.*),
    # exposed conveniently by IngestionBundle property accessors downstream.
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
```

#### Trajectory detection rules

```python
def _compute_trajectory(snapshot: MemorySnapshot, user_query: str) -> ConversationTrajectory:
    thread = snapshot.thread_memory
    clarification = snapshot.clarification_memory
    objects = snapshot.object_memory

    # Fresh start: no prior state
    if not thread.thread_id and not thread.active_route:
        return ConversationTrajectory(phase="fresh_start")

    # Clarification loop: we asked a question, waiting for answer
    if clarification.pending_clarification_type:
        return ConversationTrajectory(
            phase="clarification_loop",
            has_pending_clarification=True,
            prior_route=thread.active_route,
            prior_turn_type=thread.last_turn_type,
        )

    # Follow-up: last turn was a substantive response, user continues
    if thread.last_turn_type in {"answer", "clarification_answer"}:
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
```

### Phase 2: Reflect

Reflect runs at the end of each turn. It collects `MemoryContribution` objects from each layer, merges them, applies decay, and produces the next `MemorySnapshot`.

#### What Reflect does

1. **Collect contributions** — each layer emits a typed `MemoryContribution` describing what it wants to update
2. **Merge contributions** — combine partial updates, resolving conflicts (later layers win for overlapping fields)
3. **Apply salience decay** — increment `turn_age`, update `interaction_count` for re-referenced objects, evict objects below the salience threshold
4. **Store IntentGroups** — save this turn's IntentGroups for next-turn recall
5. **Build next snapshot** — apply merged MemoryUpdate to current snapshot
6. **Persist** — save to Redis via SessionStore

#### MemoryContribution contract

```python
class MemoryContribution(BaseModel):
    """A partial memory update from one pipeline layer.
    
    Each layer emits only the fields it is responsible for.
    The Reflect phase merges all contributions into one MemoryUpdate.
    """
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "ingestion", "objects", "routing", "executor", "response"
    ]

    # Thread state (typically from routing)
    active_route: str | None = None
    route_phase: str | None = None

    # Object state (typically from objects layer)
    set_active_object: ObjectRef | None = None
    secondary_active_objects: list[ObjectRef] | None = None
    append_recent_objects: list[ObjectRef] | None = None

    # Clarification state (typically from routing)
    set_pending_clarification: ClarificationMemory | None = None
    clear_pending_clarification: bool = False

    # Response state (typically from response layer)
    mark_revealed_attributes: list[str] | None = None
    set_last_tool_results: list[dict] | None = None
    set_last_response_topics: list[str] | None = None

    # Intent groups (typically from assembly step)
    intent_groups: list[IntentGroup] | None = None

    # Control signals
    soft_reset_current_topic: bool = False
    reason: str = ""
```

#### Contribution sources by layer

| Layer | Contributes | Fields |
| --- | --- | --- |
| **Ingestion** | Normalized query context | `reason` (for debug) |
| **Objects** | Resolved entities | `set_active_object`, `secondary_active_objects`, `append_recent_objects` |
| **Assembly** | Bound intent groups | `intent_groups` |
| **Routing** | Route decision, clarification | `active_route`, `route_phase`, `set_pending_clarification`, `clear_pending_clarification` |
| **Executor** | Tool results | `set_last_tool_results` |
| **Response** | Revealed content, topic | `mark_revealed_attributes`, `set_last_response_topics`, `soft_reset_current_topic` |

#### Reflect implementation sketch

```python
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

    # 3. Apply salience decay (increments turn_age, bumps interaction_count, evicts low-salience)
    next_snapshot = _apply_salience_decay(next_snapshot)

    # 4. Store intent groups + detect drift for next turn
    next_snapshot = _store_intent_groups_with_drift(next_snapshot, contributions)

    return next_snapshot


def _merge_contributions(
    contributions: list[MemoryContribution],
    thread_id: str,
    normalized_query: str,
    last_turn_type: str,
) -> MemoryUpdate:
    """Merge all layer contributions into one MemoryUpdate.
    
    Merge rules:
    - For scalar fields (active_route, route_phase): last writer wins
    - For list fields (append_recent_objects): concatenate + dedupe
    - For control signals (soft_reset): any True wins (OR semantics)
    """
    update = MemoryUpdate()

    # Build thread memory from contributions
    active_route = ""
    route_phase = "active"
    for c in contributions:
        if c.active_route is not None:
            active_route = c.active_route
        if c.route_phase is not None:
            route_phase = c.route_phase

    update.thread_memory = ThreadMemory(
        thread_id=thread_id,
        active_route=active_route,
        route_phase=route_phase,
        last_turn_type=last_turn_type,
        last_user_goal=normalized_query,
    )

    # Merge object contributions
    for c in contributions:
        if c.set_active_object is not None:
            update.set_active_object = c.set_active_object
        if c.secondary_active_objects is not None:
            update.secondary_active_objects = c.secondary_active_objects
        if c.append_recent_objects is not None:
            existing = update.append_recent_objects or []
            update.append_recent_objects = existing + c.append_recent_objects

    # Merge clarification
    for c in contributions:
        if c.clear_pending_clarification or c.soft_reset_current_topic:
            update.clear_pending_clarification = True
        if c.set_pending_clarification is not None:
            update.set_pending_clarification = c.set_pending_clarification

    # Merge response state
    for c in contributions:
        if c.mark_revealed_attributes is not None:
            existing = update.mark_revealed_attributes or []
            update.mark_revealed_attributes = existing + c.mark_revealed_attributes
        if c.set_last_tool_results is not None:
            update.set_last_tool_results = c.set_last_tool_results
        if c.set_last_response_topics is not None:
            existing = update.set_last_response_topics or []
            update.set_last_response_topics = existing + c.set_last_response_topics

    # Soft reset: any True wins
    if any(c.soft_reset_current_topic for c in contributions):
        update.soft_reset_current_topic = True

    # Merge reason
    reasons = [c.reason for c in contributions if c.reason]
    update.reason = "; ".join(reasons) if reasons else ""

    return update
```

#### Object salience scoring and eviction

The salience formula ensures that foundational objects (keystones of the conversation) survive turn gaps, while one-off mentions decay naturally:

```
salience = (base_weight × interaction_count) / max(turn_age, 1)
```

**Example — biotech conversation**:

| Object | base_weight | interaction_count | turn_age | salience | relevance |
| --- | --- | --- | --- | --- | --- |
| CD19 (scientific_target) | 2.5 | 5 | 3 | 4.17 | high |
| CAR-T construct (service) | 2.0 | 3 | 3 | 2.0 | high |
| Order #12345 (order) | 1.5 | 1 | 6 | 0.25 | low |
| Invoice #789 (invoice) | 1.0 | 1 | 4 | 0.25 | low |

CD19 was mentioned in 5 turns — it's a keystone. Even after 3 turns of discussing something else, it retains high salience. Order #12345 was a one-shot lookup; after 6 turns it's a candidate for eviction.

```python
def _score_recent_objects(object_memory: ObjectMemory) -> list[ScoredObjectRef]:
    """Compute salience for all recent objects. Sort by salience descending."""
    scored = []
    for ref in object_memory.recent_objects:
        turn_age = getattr(ref, "turn_age", 0)
        interaction_count = getattr(ref, "interaction_count", 1)
        base_weight = BASE_WEIGHT_MAP.get(ref.object_type, 1.0)
        salience = (base_weight * interaction_count) / max(turn_age, 1)

        if salience >= 2.0:
            relevance = "high"
        elif salience >= 0.5:
            relevance = "medium"
        else:
            relevance = "low"

        scored.append(ScoredObjectRef(
            object_ref=ref,
            turn_age=turn_age,
            interaction_count=interaction_count,
            base_weight=base_weight,
            is_active=(ref == object_memory.active_object),
            salience=salience,
            relevance=relevance,
        ))

    scored.sort(key=lambda s: s.salience, reverse=True)
    return scored


def _apply_salience_decay(snapshot: MemorySnapshot) -> MemorySnapshot:
    """Increment turn_age, update interaction_count, evict low-salience objects."""
    EVICTION_THRESHOLD = 0.3    # below this, object is evicted
    MAX_RECENT_OBJECTS = 15     # hard cap (raised from 10 to accommodate keystones)

    objects = snapshot.object_memory

    # Identify objects referenced this turn (active + secondary)
    referenced_ids = set()
    if objects.active_object:
        referenced_ids.add(_object_key(objects.active_object))
    for ref in objects.secondary_active_objects:
        referenced_ids.add(_object_key(ref))

    surviving = []
    for ref in objects.recent_objects:
        key = _object_key(ref)

        # Increment turn_age for all; bump interaction_count for referenced ones
        new_age = getattr(ref, "turn_age", 0) + 1
        new_count = getattr(ref, "interaction_count", 1)
        if key in referenced_ids:
            new_count += 1
            new_age = 1  # reset age when re-referenced

        base_weight = BASE_WEIGHT_MAP.get(ref.object_type, 1.0)
        salience = (base_weight * new_count) / max(new_age, 1)

        if salience >= EVICTION_THRESHOLD:
            surviving.append(ref.model_copy(update={
                "turn_age": new_age,
                "interaction_count": new_count,
            }))

    # Hard cap: keep top by salience
    if len(surviving) > MAX_RECENT_OBJECTS:
        surviving.sort(
            key=lambda r: (BASE_WEIGHT_MAP.get(r.object_type, 1.0) * getattr(r, "interaction_count", 1))
                          / max(getattr(r, "turn_age", 0), 1),
            reverse=True,
        )
        surviving = surviving[:MAX_RECENT_OBJECTS]

    return snapshot.model_copy(deep=True, update={
        "object_memory": objects.model_copy(update={
            "recent_objects": surviving,
        })
    })
```

### IntentGroup Continuity

This is the key v3 addition that solves the "multi-turn group continuity" gap identified in the ingestion design.

#### Storage

IntentGroups from the current turn are stored in a new `IntentMemory` sub-memory:

```python
class IntentMemory(BaseModel):
    """Tracks intent groups across turns for follow-up continuity."""
    model_config = ConfigDict(extra="forbid")

    prior_intent_groups: list[IntentGroup] = Field(default_factory=list)
    prior_primary_intent: str = "unknown"
    turns_since_last_intent_change: int = 0
```

#### How it enables follow-up

```
Turn 1: "Check my order #12345 and explain the CAR-T construct mechanism"
  → IntentGroups:
    [0] order_support → order #12345
    [1] technical_question → CAR-T
  → Stored in IntentMemory.prior_intent_groups

Turn 2: "Tell me more about the second thing"
  → Recall surfaces prior_intent_groups
  → Reference signals detect "the second thing" as index reference
  → Object resolution: MemoryContext.recent_objects_by_relevance carries CAR-T as scored secondary context
  → Assembly: produces IntentGroup(technical_question, CAR-T) with continuity
```

The recall phase provides `prior_intent_groups` in `MemoryContext`. The ingestion layer's reference signal detection can use this to resolve ordinal references ("the first one", "the second thing"). The assembly step can check whether the current turn's flags overlap with prior groups to maintain topic continuity.

#### When IntentGroups are replaced vs. preserved

| Scenario | Action |
| --- | --- |
| User sends a new multi-intent query | Replace prior_intent_groups with new ones |
| User follows up on one specific group | Keep all prior groups, mark followed-up group |
| User says "thanks" / closing | Clear prior_intent_groups (soft reset) |
| Clarification answer | Preserve prior groups (clarification is for the same intents) |

### Intent Drift Detection

A key problem in multi-turn conversations: the user says "tell me more" (apparent follow-up), then appends something tangential. Without drift detection, the agent confidently routes to the prior topic's tools — a **continuity hallucination**.

#### The problem

```
Turn 1: "Explain the CAR-T construct for CD19 targeting"
  → IntentGroups: [technical_question → CAR-T / CD19]

Turn 2: "Tell me more... also what's the price of product 20001?"
  → Without drift detection: assembly treats this as continuation of CAR-T topic
  → With drift detection: continuity_confidence drops, assembly creates a new group for product 20001
```

#### Drift scoring

The recall phase computes a `continuity_confidence` score by comparing the current turn's signals against prior IntentGroups:

```python
class IntentDriftResult(BaseModel):
    """Result of intent drift detection."""
    model_config = ConfigDict(extra="forbid")

    continuity_confidence: float = 0.0    # 0.0 = full drift, 1.0 = perfect continuity
    drift_action: Literal[
        "preserve",     # high confidence: keep prior groups as-is
        "merge",        # moderate confidence: keep prior groups, add new ones
        "stack",        # low confidence: push prior groups to history, start fresh
        "clear",        # no confidence: discard prior groups entirely
    ] = "clear"
    resolved_groups: list[IntentGroup] = Field(default_factory=list)
    reason: str = ""


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
            resolved_groups=prior_groups,
            reason="clarification loop: groups unchanged",
        )

    # Follow-up or mid-topic: compute overlap score
    query_lower = user_query.lower()
    overlap_signals = _compute_overlap_signals(query_lower, prior_groups)

    if overlap_signals.score >= 0.7:
        return IntentDriftResult(
            continuity_confidence=overlap_signals.score,
            drift_action="preserve",
            resolved_groups=prior_groups,
            reason=f"high overlap: {overlap_signals.matched_signals}",
        )
    elif overlap_signals.score >= 0.3:
        return IntentDriftResult(
            continuity_confidence=overlap_signals.score,
            drift_action="merge",
            resolved_groups=prior_groups,
            reason=f"moderate overlap: {overlap_signals.matched_signals}",
        )
    elif overlap_signals.score > 0:
        return IntentDriftResult(
            continuity_confidence=overlap_signals.score,
            drift_action="stack",
            resolved_groups=[],  # prior groups stacked, not surfaced
            reason=f"low overlap, stacking: {overlap_signals.matched_signals}",
        )
    else:
        return IntentDriftResult(
            continuity_confidence=0.0,
            drift_action="clear",
            resolved_groups=[],
            reason="no overlap with prior groups",
        )
```

#### Overlap signal computation

```python
class OverlapSignals(BaseModel):
    score: float = 0.0                # 0.0–1.0
    matched_signals: list[str] = Field(default_factory=list)


def _compute_overlap_signals(
    query_lower: str,
    prior_groups: list[IntentGroup],
) -> OverlapSignals:
    """Compute semantic overlap between current query and prior IntentGroups.
    
    Uses deterministic signals (no LLM):
    - Entity name overlap (object_identifier, object_display_name mentioned in query)
    - Intent keyword overlap (prior intent keywords appear in query)
    - Follow-up language detection ("more", "also", "continue", "about that")
    """
    signals: list[str] = []
    score = 0.0

    # 1. Entity name overlap (strongest signal)
    for group in prior_groups:
        name = (group.object_display_name or group.object_identifier or "").lower()
        if name and name in query_lower:
            signals.append(f"entity_match:{name}")
            score += 0.4

    # 2. Follow-up language (moderate signal)
    follow_up_phrases = [
        "tell me more", "more about", "continue", "go on",
        "also", "additionally", "what else", "can you elaborate",
        "about that", "regarding that", "the same",
        "再说说", "继续", "还有", "关于这个", "接着说",
    ]
    if any(phrase in query_lower for phrase in follow_up_phrases):
        signals.append("follow_up_language")
        score += 0.3

    # 3. Intent keyword overlap (weak signal)
    prior_intents = {g.intent for g in prior_groups}
    intent_keywords = {
        "technical_question": ["mechanism", "protocol", "how does", "explain"],
        "pricing_question": ["price", "cost", "quote", "how much"],
        "order_support": ["order", "status", "tracking"],
        "product_inquiry": ["available", "offer", "product"],
    }
    for intent in prior_intents:
        keywords = intent_keywords.get(intent, [])
        if any(kw in query_lower for kw in keywords):
            signals.append(f"intent_keyword:{intent}")
            score += 0.15

    # 4. New entity detection (negative signal — drift indicator)
    # If the query introduces a clearly new entity not in prior groups, reduce score
    prior_entities = {
        (g.object_identifier or "").lower()
        for g in prior_groups
    } | {
        (g.object_display_name or "").lower()
        for g in prior_groups
    }
    prior_entities.discard("")
    # Simple heuristic: if query has a catalog-number-like pattern not in prior entities
    import re
    new_identifiers = re.findall(r'\b(?:pm-)?[a-z]*\d{4,}\b', query_lower)
    for nid in new_identifiers:
        if nid not in prior_entities:
            signals.append(f"new_entity:{nid}")
            score -= 0.3

    return OverlapSignals(
        score=max(0.0, min(1.0, score)),
        matched_signals=signals,
    )
```

#### Drift actions explained

| Action | Condition | Effect on IntentMemory | Effect on MemoryContext |
| --- | --- | --- | --- |
| **preserve** | High overlap (≥ 0.7) | Keep prior_intent_groups as-is | Surface all prior groups |
| **merge** | Moderate overlap (0.3–0.7) | Keep prior groups, new groups added alongside | Surface prior + new groups |
| **stack** | Low overlap (> 0, < 0.3) | Push prior groups to `stacked_intent_history` | Surface only new groups |
| **clear** | No overlap or fresh start | Discard prior groups | Empty prior_intent_groups |

**Stack** is the key innovation: instead of binary keep/discard, low-drift prior groups are preserved in a secondary history. If the user later says "go back to what we were discussing", the stacked groups can be restored.

```python
class IntentMemory(BaseModel):
    """Tracks intent groups across turns for follow-up continuity."""
    model_config = ConfigDict(extra="forbid")

    prior_intent_groups: list[IntentGroup] = Field(default_factory=list)
    stacked_intent_history: list[list[IntentGroup]] = Field(default_factory=list)  # stack of stacked groups
    prior_primary_intent: str = "unknown"
    continuity_confidence: float = 0.0
    turns_since_last_intent_change: int = 0
```

#### How assembly uses continuity_confidence

The assembly step reads `memory_context.intent_continuity_confidence` to decide how aggressively to reuse prior groups:

```python
def assemble_intent_groups(
    request_flags: ParserRequestFlags,
    resolved_objects: list,
    primary_intent: str = "unknown",
    *,
    prior_intent_groups: list[IntentGroup] | None = None,
    continuity_confidence: float = 0.0,
) -> list[IntentGroup]:
    """Deterministically bind active request_flags to resolved objects."""
    active_flags = _get_active_flags(request_flags)

    # If no active flags AND high continuity, this is a pure follow-up
    if not active_flags and continuity_confidence >= 0.7 and prior_intent_groups:
        # Inherit prior groups (user said "tell me more" without new intent signals)
        return prior_intent_groups

    # If moderate continuity, merge: assemble new groups + keep unmatched prior groups
    groups = _assemble_from_flags(active_flags, resolved_objects, primary_intent)
    if continuity_confidence >= 0.3 and prior_intent_groups:
        groups = _merge_with_prior(groups, prior_intent_groups)

    # If low/no continuity, just return freshly assembled groups
    return groups or _single_group_from_intent(primary_intent, resolved_objects)
```

This ensures the assembly step respects drift signals from memory rather than blindly trusting prior IntentGroups.

### Eliminating route_state duplication

Currently, both `memory_snapshot` and `route_state` are persisted separately to Redis. They can diverge.

In v3:
- `MemorySnapshot` is the **only** persisted entity
- `route_state` is computed on demand via `snapshot_to_route_state()`
- Modules that currently read `route_state` should read from `MemoryContext` instead
- `snapshot_to_route_state()` remains available as a backward-compatibility bridge during migration

```python
# v2 (current): persist both
session_store.update_memory_snapshot(thread_id, next_snapshot)
session_store.update_route_state(thread_id, route_state)  # can diverge!

# v3: persist snapshot only, derive route_state when needed
session_store.update_memory_snapshot(thread_id, next_snapshot)
# route_state = snapshot_to_route_state(next_snapshot)  # computed, not stored
```

## Data Contracts

### New models

```python
class IntentMemory(BaseModel):
    """Tracks intent groups across turns with drift detection."""
    model_config = ConfigDict(extra="forbid")

    prior_intent_groups: list[IntentGroup] = Field(default_factory=list)
    stacked_intent_history: list[list[IntentGroup]] = Field(default_factory=list)
    prior_primary_intent: str = "unknown"
    continuity_confidence: float = 0.0
    turns_since_last_intent_change: int = 0


class ConversationTrajectory(BaseModel):
    """Conversation flow phase detection."""
    model_config = ConfigDict(extra="forbid")

    phase: Literal[
        "fresh_start", "mid_topic", "clarification_loop",
        "follow_up", "topic_switch",
    ] = "fresh_start"
    turns_on_current_topic: int = 0
    has_pending_clarification: bool = False
    prior_route: str = ""
    prior_turn_type: str = ""


class ScoredObjectRef(BaseModel):
    """ObjectRef with salience scoring for prioritized surfacing."""
    model_config = ConfigDict(extra="forbid")

    object_ref: ObjectRef
    turn_age: int = 0
    interaction_count: int = 1
    base_weight: float = 1.0
    is_active: bool = False
    salience: float = 1.0
    relevance: Literal["high", "medium", "low"] = "low"


class IntentDriftResult(BaseModel):
    """Result of intent drift detection."""
    model_config = ConfigDict(extra="forbid")

    continuity_confidence: float = 0.0
    drift_action: Literal["preserve", "merge", "stack", "clear"] = "clear"
    resolved_groups: list[IntentGroup] = Field(default_factory=list)
    reason: str = ""


class MemoryContext(BaseModel):
    """Enriched memory view produced by recall().
    Single entry point for all downstream modules.
    Sub-memory access (e.g., thread_memory.active_route,
    clarification_memory.pending_candidate_options) goes through
    `MemoryContext.snapshot`, not a separate StatefulAnchors wrapper."""
    model_config = ConfigDict(extra="forbid")

    snapshot: MemorySnapshot
    prior_intent_groups: list[IntentGroup] = Field(default_factory=list)
    intent_continuity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    trajectory: ConversationTrajectory = Field(default_factory=ConversationTrajectory)
    active_object: ObjectRef | None = None
    recent_objects_by_relevance: list[ScoredObjectRef] = Field(default_factory=list)
    revealed_attributes: list[str] = Field(default_factory=list)
    last_response_topics: list[str] = Field(default_factory=list)
    prior_demand_type: str = "general"
    prior_demand_flags: list[str] = Field(default_factory=list)


class MemoryContribution(BaseModel):
    """Partial memory update from one pipeline layer."""
    model_config = ConfigDict(extra="forbid")

    source: Literal["ingestion", "objects", "routing", "executor", "response"]
    active_route: str | None = None
    route_phase: str | None = None
    set_active_object: ObjectRef | None = None
    secondary_active_objects: list[ObjectRef] | None = None
    append_recent_objects: list[ObjectRef] | None = None
    set_pending_clarification: ClarificationMemory | None = None
    clear_pending_clarification: bool = False
    mark_revealed_attributes: list[str] | None = None
    set_last_tool_results: list[dict] | None = None
    set_last_response_topics: list[str] | None = None
    intent_groups: list[IntentGroup] | None = None
    soft_reset_current_topic: bool = False
    reason: str = ""
```

### Updated models

```python
class MemorySnapshot(BaseModel):
    """Canonical typed state. Single source of truth."""
    model_config = ConfigDict(extra="forbid")

    thread_memory: ThreadMemory = Field(default_factory=ThreadMemory)
    object_memory: ObjectMemory = Field(default_factory=ObjectMemory)
    clarification_memory: ClarificationMemory = Field(default_factory=ClarificationMemory)
    response_memory: ResponseMemory = Field(default_factory=ResponseMemory)
    intent_memory: IntentMemory = Field(default_factory=IntentMemory)   # NEW
```

```python
class ObjectRef(BaseModel):
    """Lightweight entity pointer in memory."""
    # Existing fields
    object_type: str = ""
    identifier: str = ""
    display_name: str = ""
    business_line: str = ""
    # NEW: salience tracking
    turn_age: int = 0               # turns since last referenced
    interaction_count: int = 1      # how many turns have referenced this object
```

### Unchanged models

- `ThreadMemory` — fields unchanged
- `ClarificationMemory` — fields unchanged
- `ResponseMemory` — fields unchanged
- `MemoryUpdate` — fields unchanged (IntentMemory updates go through the new Reflect path)
- ~~`StatefulAnchors`~~ — **removed**. Sub-memory state is now reached through `MemoryContext.snapshot.thread_memory` / `MemoryContext.snapshot.clarification_memory` (typically via the `IngestionBundle.thread_memory` / `clarification_memory` property accessors).

## Integration With Other Modules

### Memory → Ingestion

**What memory provides**: `MemoryContext.snapshot.thread_memory` + `MemoryContext.snapshot.clarification_memory` + `MemoryContext.trajectory`

**How ingestion uses it**:
- `snapshot.thread_memory.active_route` / `active_business_line` → reference signal detection (`requires_active_context_for_safe_resolution`)
- `snapshot.clarification_memory.pending_clarification_type` / `pending_candidate_options` → parser can resolve a user's selection answer when a clarification loop is open
- `trajectory.phase` → if `clarification_loop`, ingestion can adjust parser behavior (expect a disambiguation answer, not a new query)
- `trajectory.phase` → if `follow_up`, reference signals are more aggressive about accepting pronoun resolution

**Contract**: `recall()` produces `MemoryContext`. The ingestion bundle exposes the relevant sub-memories directly via property accessors, so downstream code reads them as plain attributes:

```python
memory_context = recall(thread_id=thread_id, user_query=query, prior_state=prior_state)
ingestion_bundle = build_ingestion_bundle(memory_context=memory_context, ...)

# Downstream callers read prior state through bundle properties, e.g.:
#   ingestion_bundle.thread_memory.active_route
#   ingestion_bundle.clarification_memory.pending_candidate_options
# Both proxy onto memory_context.snapshot.* — no separate StatefulAnchors wrapper.
```

**What ingestion contributes back**: `MemoryContribution(source="ingestion", reason="...")` — minimal, mainly debug context.

### Memory → Objects

**What memory provides**: `MemoryContext.active_object` + `MemoryContext.recent_objects_by_relevance`

**How objects uses it**:
- `active_object` → if user says "this product", resolve to the active object from memory
- `recent_objects_by_relevance` → if user says "the other one", the objects layer can check recent history for alternatives
- `snapshot.clarification_memory.pending_candidate_options` → if we're in a clarification loop, the user's answer selects from the pending candidates (typically read via `IngestionBundle.clarification_memory`)

**What objects contributes back**:
```python
MemoryContribution(
    source="objects",
    set_active_object=resolved_object_state.primary_object_ref,
    secondary_active_objects=[obj.to_ref() for obj in resolved_object_state.secondary_objects],
    append_recent_objects=[primary_ref, *secondary_refs],
)
```

### Memory → Intent Assembly

**What memory provides**: `MemoryContext.prior_intent_groups`

**How assembly uses it**:
- If the current turn has no active flags but the prior turn had IntentGroups, assembly can check whether this is a follow-up on one of those groups
- If the user references "the second thing", assembly can use the ordinal to index into `prior_intent_groups`

**What assembly contributes back**:
```python
MemoryContribution(
    source="ingestion",  # assembly is logically part of ingestion
    intent_groups=current_intent_groups,
)
```

### Memory → Routing

**What memory provides**: `MemoryContext.trajectory` + `MemoryContext.snapshot.thread_memory.active_route`

**How routing uses it**:
- `trajectory.has_pending_clarification` → if True and user provides new input, routing can decide whether this is a clarification answer or a topic switch
- `active_route` → continuity signal for route phase management

**What routing contributes back**:
```python
MemoryContribution(
    source="routing",
    active_route=route_decision.route_name,
    # v4: route_decision.action is always coerced to "execute" before this
    # contribution is built, so a "waiting_for_user" phase can NOT be derived
    # from the routing action. The phase is instead derived from what the
    # responser actually rendered: a `clarification` or `partial_answer`
    # response_type means we are waiting on the user, anything else (in
    # particular `csr_draft`) is `active`.
    route_phase="waiting_for_user" if final_response.response_type in ("clarification", "partial_answer") else "active",
    set_pending_clarification=clarification_payload,  # or clear_pending_clarification=True
)
```

### Memory → Executor

**What memory provides**: `MemoryContext.revealed_attributes` (avoid re-fetching known information)

**How executor uses it** (optional optimization):
- If `revealed_attributes` already includes "product_price", the executor can skip the pricing tool unless the user explicitly asks again

**What executor contributes back**:
```python
MemoryContribution(
    source="executor",
    set_last_tool_results=[result.model_dump() for result in tool_results],
)
```

### Memory → Response

**What memory provides**: `MemoryContext.revealed_attributes` + `MemoryContext.last_response_topics`

**How response uses it**:
- Avoid repeating the same information across turns
- Adapt response length (if we already covered basics, be concise on follow-up)

**What response contributes back**:
```python
MemoryContribution(
    source="response",
    mark_revealed_attributes=["product_name", "product_price", "storage_conditions"],
    set_last_response_topics=["pricing_question"],
    soft_reset_current_topic=True,  # if termination mode
)
```

## Pipeline Integration

### Where recall and reflect fit

```python
# service.py (v3 orchestration)

async def run_agent_turn(request: AgentRequest) -> AgentResponse:
    # ── RECALL ──────────────────────────────────────────────
    memory_context = recall(
        thread_id=request.thread_id,
        user_query=request.user_query,
        prior_state=request.prior_state,
    )

    # ── INGESTION ───────────────────────────────────────────
    ingestion_bundle = build_ingestion_bundle(
        memory_context=memory_context,
        user_query=request.user_query,
        conversation_history=request.conversation_history,
        attachments=request.attachments,
    )

    # ── OBJECTS ─────────────────────────────────────────────
    resolved_object_state = resolve_objects(ingestion_bundle)

    # ── ASSEMBLY ────────────────────────────────────────────
    intent_groups = assemble_intent_groups(
        request_flags=ingestion_bundle.turn_signals.parser_signals.request_flags,
        resolved_objects=_all_resolved(resolved_object_state),
        primary_intent=ingestion_bundle.turn_signals.parser_signals.context.primary_intent,
    )

    # ── ROUTING ─────────────────────────────────────────────
    route_decision = route_v3(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved_object_state,
        memory_context=memory_context,
    )

    # ── EXECUTOR ────────────────────────────────────────────
    execution_result = execute(
        intent_groups=intent_groups,
        resolved_object_state=resolved_object_state,
        route_decision=route_decision,
        memory_context=memory_context,
    )

    # ── RESPONSE ────────────────────────────────────────────
    response = build_response(
        route_decision=route_decision,
        execution_result=execution_result,
        ingestion_bundle=ingestion_bundle,
        memory_context=memory_context,
    )

    # ── REFLECT ─────────────────────────────────────────────
    contributions = [
        _objects_contribution(resolved_object_state),
        _assembly_contribution(intent_groups),
        _routing_contribution(route_decision),
        _executor_contribution(execution_result),
        _response_contribution(response),
    ]

    next_snapshot = reflect(
        current_snapshot=memory_context.snapshot,
        contributions=contributions,
        thread_id=request.thread_id,
        normalized_query=ingestion_bundle.turn_core.normalized_query,
        last_turn_type=response.response_type,
    )

    # ── PERSIST ─────────────────────────────────────────────
    session_store.update_memory_snapshot(request.thread_id, next_snapshot)

    return response
```

### LangChain integration

Both recall and reflect are deterministic — no LLM calls. They fit naturally as `RunnableLambda` steps:

```python
from langchain_core.runnables import RunnableLambda

def build_agent_chain():
    """Full agent turn as a LangChain chain."""

    recall_step = RunnableLambda(
        lambda state: {
            **state,
            "memory_context": recall(
                thread_id=state["thread_id"],
                user_query=state["user_query"],
                prior_state=state.get("prior_state"),
            ),
        }
    )

    ingest_step = RunnableLambda(
        lambda state: {
            **state,
            "ingestion_bundle": build_ingestion_bundle(
                memory_context=state["memory_context"],
                user_query=state["user_query"],
                conversation_history=state.get("conversation_history"),
            ),
        }
    )

    # ... resolve, assemble, route, execute, respond ...

    reflect_step = RunnableLambda(
        lambda state: {
            **state,
            "next_snapshot": reflect(
                current_snapshot=state["memory_context"].snapshot,
                contributions=state["contributions"],
                thread_id=state["thread_id"],
                normalized_query=state["ingestion_bundle"].turn_core.normalized_query,
                last_turn_type=state["response"].response_type,
            ),
        }
    )

    return recall_step | ingest_step | ... | reflect_step
```

Memory is the **first** and **last** step in the chain. Every other step runs between recall and reflect, consuming `MemoryContext` and emitting `MemoryContribution`.

## Migration Steps

### Step 1: Add IntentMemory and salience fields to models (zero risk, additive)

1. Create `IntentMemory` model in `models.py` (with `stacked_intent_history`, `continuity_confidence`)
2. Add `intent_memory: IntentMemory` field to `MemorySnapshot` with default factory
3. Existing snapshots in Redis deserialize fine (Pydantic fills defaults for missing fields)
4. Add `turn_age: int = 0` and `interaction_count: int = 1` to `ObjectRef`
5. Create `IntentDriftResult`, `ScoredObjectRef` (with salience fields), `BASE_WEIGHT_MAP`

### Step 2: Add MemoryContext and ConversationTrajectory models (zero risk, additive)

1. Create `MemoryContext`, `ConversationTrajectory`, `ScoredObjectRef` models in `models.py`
2. No consumers yet — just the data contracts

### Step 3: Implement recall() (medium risk, new entry point)

1. Create `src/memory/recall.py` with `recall()` function
2. Drop the `StatefulAnchors` wrapper. Downstream prior-state reads switch to `MemoryContext.snapshot.thread_memory` / `snapshot.clarification_memory`, exposed via `IngestionBundle.thread_memory` / `clarification_memory` property accessors.
3. Add trajectory detection logic
4. Add salience scoring (`_score_recent_objects` with `BASE_WEIGHT_MAP`)
5. Add intent drift detection (`_detect_intent_drift`, `_compute_overlap_signals`)
6. Test: verify modules previously consuming `StatefulAnchors` continue to work against the new sub-memory accessors with no behavioral change.
7. Test: verify salience scoring ranks multi-referenced objects higher than one-shot mentions
8. Test: verify drift detection correctly classifies preserve/merge/stack/clear scenarios

### Step 4: Add MemoryContribution model (zero risk, additive)

1. Create `MemoryContribution` model in `models.py`
2. No consumers yet

### Step 5: Implement reflect() (medium risk, replaces _build_memory_update)

1. Create `src/memory/reflect.py` with `reflect()` and `_merge_contributions()`
2. Add salience-based decay logic (`_apply_salience_decay` with interaction_count bumping)
3. Add IntentGroup storage with drift-aware stack/clear logic (`_store_intent_groups_with_drift`)
4. Test: verify `reflect()` with equivalent contributions produces the same snapshot as current `_build_memory_update()` + `apply_memory_update()`
5. Test: verify high-interaction objects survive longer than one-shot mentions
6. Test: verify intent groups are stacked (not discarded) on moderate drift

### Step 6: Wire recall/reflect into service.py (behavioral change)

1. Replace `load_memory_snapshot()` + the prior `extract_stateful_anchors()` step with a single `recall()` call. Downstream reads of prior state move to `IngestionBundle.thread_memory` / `clarification_memory`.
2. Replace `_build_memory_update()` + `apply_memory_update()` with layer contributions + `reflect()`
3. Run full test suite
4. Verify Redis persistence produces equivalent snapshots

### Step 7: Deprecate view.py SimpleNamespace helpers (cleanup)

1. Modules that used `active_entity_from_memory_snapshot()` switch to `memory_context.active_object`
2. Modules that used `pending_clarification_from_memory_snapshot()` switch to `memory_context.snapshot.clarification_memory` (most call sites read this through `IngestionBundle.clarification_memory`)
3. Keep view.py functions for backward compatibility during migration, mark as deprecated

### Step 8: Remove route_state dual persistence (cleanup)

1. Stop persisting `route_state` separately in Redis
2. Compute `route_state` on demand from `MemorySnapshot` for any v2 code that still reads it
3. Remove `update_route_state()` from SessionStore

## Known Limitations

### Trajectory detection is heuristic

`_compute_trajectory()` uses simple rules (has active_object → mid_topic, has pending_clarification → clarification_loop). It cannot detect subtle topic switches like:

```
Turn 1: "Tell me about product A"
Turn 2: "What about product B?" (topic switch, but active_object is still A until objects resolves B)
```

The trajectory is computed _before_ ingestion runs, so it can't know about new entities yet. This is acceptable — trajectory is a hint for downstream modules, not a hard constraint.

### Salience scoring is turn-based, not time-based

`turn_age` increments per turn, not per elapsed time. A 2-hour gap between turns has the same decay as a 2-second gap. For email-based conversations (which are the primary use case), this is fine — turns are the natural unit of conversation progression. If real-time conversations become a primary use case, `turn_age` could be replaced or supplemented with a time-based decay factor.

### Intent drift detection is keyword-based

`_compute_overlap_signals()` uses keyword matching and follow-up phrase detection, not semantic similarity. This means it cannot detect subtle semantic drift (e.g., "tell me about the other protein" — new entity but same domain). For v3, keyword-based detection is sufficient for common patterns. A future enhancement could use lightweight embedding similarity between the current query and prior IntentGroup descriptions.

### Stacked intent history has no depth limit

`stacked_intent_history` accumulates stacked groups without bound. In practice, conversations rarely exceed 10-15 turns, so the stack stays small. If long conversations become common, add a depth limit (e.g., keep last 3 stacked layers).

### IntentGroup continuity requires ordinal resolution

"Tell me more about the second thing" requires the ingestion layer to:
1. Detect "the second thing" as an ordinal reference
2. Map ordinal=2 to `prior_intent_groups[1]`

This ordinal resolution is not yet implemented in reference signals. The infrastructure (prior_intent_groups in MemoryContext) is in place, but the consumer logic is deferred.

### MemoryContribution merge order matters

Contributions are merged in list order. If two layers set `set_active_object` to different values, the later one wins. The pipeline must emit contributions in a deterministic order:

```
ingestion → objects → assembly → routing → executor → response
```

This matches the natural execution order.

### No cross-thread memory

Memory is scoped to a single `thread_id`. If a customer sends two separate email threads about the same product, each thread has independent memory. Cross-thread intelligence (e.g., "this customer has asked about CAR-T in 3 different threads") is out of scope for v3.

## Anti-Patterns

1. **Reading raw MemorySnapshot in downstream modules.** Use `MemoryContext` from `recall()`. MemoryContext provides prioritized, typed views — don't bypass it to read raw snapshot fields.

2. **Building MemoryUpdate directly in service.py.** Emit `MemoryContribution` from each layer and let `reflect()` merge them. The orchestrator should not know the internal update rules of each sub-memory.

3. **Persisting route_state separately.** `MemorySnapshot` is the single source of truth. `route_state` is a computed view for backward compatibility, not a parallel state.

4. **LLM calls in recall or reflect.** Both phases are deterministic. Memory reasoning is rule-based: trajectory detection, decay scoring, contribution merging. If you need an LLM to decide what to remember, the signal extraction upstream (ingestion/objects) should be richer, not the memory layer smarter.

5. **Storing tool results in full.** `set_last_tool_results` should store summaries or keys, not full `ToolResult` objects. Memory is for context across turns, not a result cache.

6. **Mutating MemorySnapshot mid-turn.** The snapshot from `recall()` is frozen for the entire turn. All changes flow through `MemoryContribution` → `reflect()` → next snapshot. No mid-pipeline writes.

7. **Using SimpleNamespace views for new code.** `view.py` helpers return untyped `SimpleNamespace`. New code should use `MemoryContext` fields (typed, validated). SimpleNamespace views exist only for backward compatibility during migration.

## Target File Structure

```
src/memory/
├── __init__.py                    # Public API exports
├── models.py                      # All data models (+ IntentMemory, MemoryContext, etc.)
├── recall.py                      # NEW: recall() entry point
├── reflect.py                     # NEW: reflect() + _merge_contributions()
├── store.py                       # load / apply / serialize (internal)
├── session_store.py               # Redis-backed session management
├── adapters/
│   ├── __init__.py
│   └── redis_store.py             # Redis adapter
├── thread_memory.py               # Thread-level update logic
├── object_memory.py               # Object-level update logic (+ decay)
├── clarification_memory.py        # Clarification state updates
├── response_memory.py             # Response history updates
└── view.py                        # DEPRECATED: SimpleNamespace helpers
```
