# Memory Layer Design

## Goal

The memory layer should store only the state that later turns can actually use.

Its purpose is to answer one question:

> What typed state from prior turns should still influence the current turn?

In short:

- `memory` preserves reusable state
- `ingestion` converts that state into `stateful_anchors`
- `objects` and `routing` consume those anchors

This is not meant to be an unbounded transcript store.

## Position In The Stack

The intended architecture order is:

1. `memory`
2. `ingestion`
3. `objects`
4. `routing`
5. `tools`
6. `execution`
7. `response`

More precisely:

- `memory` exposes a typed snapshot
- `ingestion` converts relevant parts of that snapshot into `stateful_anchors`
- downstream layers consume those anchors rather than reading memory directly

## Boundary

### In Scope

The memory layer should:

1. preserve thread continuity state
2. preserve active and recent object state
3. preserve pending clarification state
4. preserve response-progress state such as revealed attributes
5. expose one typed memory snapshot
6. accept one typed memory update after each turn

### Out Of Scope

The memory layer should not:

- perform object extraction
- perform object resolution
- choose tools
- generate retrieval queries
- generate final answers
- act like a second routing layer

## Design Principle

Memory should be typed and purposeful.

That means:

- store only state that later layers actually use
- distinguish different classes of state explicitly
- avoid one giant session blob with mixed semantics

The memory layer should not be:

- a loose dict of convenience fields
- an unbounded copy of the entire conversation
- a place where routing logic quietly hides

## Canonical Naming

The memory layer should align to the current architecture vocabulary:

- `stateful_anchors`
- `active_object`
- `secondary_active_objects`
- `pending_clarification`
- `candidate_object_sets`
- `revealed_attributes`
- `last_tool_results`
- `MemorySnapshot`
- `MemoryUpdate`

## Core State Families

The memory layer should be split into four main state families.

### 1. Thread Memory

This stores high-level continuity state for the thread.

Suggested fields:

```python
{
    "thread_id": str,
    "active_route": str,
    "continuity_mode": str,
    "last_turn_type": str,
    "last_user_goal": str,
    "active_business_line": str,
}
```

Use cases:

- detecting follow-ups
- detecting clarification replies
- preserving high-level continuity

### 2. Object Memory

This stores object continuity state.

Suggested fields:

```python
{
    "active_object": dict | None,
    "secondary_active_objects": list[dict],
    "recent_objects": list[dict],
    "candidate_object_sets": list[dict],
}
```

Use cases:

- `this one`
- `that service`
- `32122`
- carrying an active product or service across turns

### 3. Clarification Memory

This stores pending clarification state explicitly.

Suggested fields:

```python
{
    "pending_clarification_type": str,
    "pending_candidate_options": list[str],
    "pending_identifier": str,
    "pending_question": str,
    "pending_route_after_clarification": str,
}
```

Examples of clarification types:

- `product_selection`
- `service_selection`
- `referential_scope`
- `identifier_type`

Use cases:

- interpreting `32122`
- interpreting `the first one`
- determining what the user is answering

### 4. Response Memory

This stores short-term conversational response state.

Suggested fields:

```python
{
    "revealed_attributes": list[str],
    "last_tool_results": list[dict],
    "last_response_topics": list[str],
}
```

Use cases:

- making `ELABORATE` move to the next layer of detail
- preventing repetitive answers
- supporting soft termination of the current topic

## Core Contracts

### `StatefulAnchors`

This is the part of memory that ingestion should expose downstream.

Suggested shape:

```python
{
    "active_route": dict | None,
    "active_business_line": dict | None,
    "active_entity_kind": dict | None,
    "active_entity_identifier": dict | None,
    "pending_clarification_field": dict | None,
    "pending_candidate_options": list[dict],
    "pending_identifier": dict | None,
    "last_user_goal": dict | None,
}
```

Important rule:

- `stateful_anchors` are contextual constraints
- they are not fresh evidence
- they should always be marked as `CONTEXTUAL`

### `MemorySnapshot`

The memory layer should expose one typed snapshot, for example:

```python
{
    "thread_memory": {...},
    "object_memory": {...},
    "clarification_memory": {...},
    "response_memory": {...},
}
```

This is the full internal memory view.

### `MemoryUpdate`

The memory layer should also accept one typed update contract after each turn.

Suggested shape:

```python
{
    "set_active_object": dict | None,
    "append_recent_objects": list[dict],
    "set_pending_clarification": dict | None,
    "clear_pending_clarification": bool,
    "mark_revealed_attributes": list[str],
    "set_last_tool_results": list[dict],
    "soft_reset_current_topic": bool,
    "reason": str,
}
```

This keeps writes explicit and auditable.

## Architectural Rule

Downstream layers should not read session storage directly.

Instead:

- `memory` owns state persistence
- `ingestion` converts memory into `stateful_anchors`
- `objects`, `routing`, `tools`, and `response` consume the resulting typed contracts

This rule is especially important for:

- `objects`
- `routing`
- `tools`

They should not re-open Redis or other storage to rediscover state on their own.

## Short-Term vs Long-Term State

Not all state should be treated equally.

### Short-Term State

Short-lived and easy to clear:

- pending clarification
- candidate options
- last tool results
- last response topics

### Mid-Term State

Should survive follow-ups but may be reset on topic change:

- active object
- revealed attributes
- active route

### Long-Term State

Useful for broader continuity but should not dominate current-turn interpretation:

- recent objects
- continuity summaries
- historical business line preference

## Soft Reset

The system should support a soft reset instead of wiping the entire thread.

This is especially useful for:

- `TERMINATE`
- `stop`
- `that's all`
- `别说了`

### Soft Reset Scope

Suggested fields to clear:

- `active_object`
- `pending_clarification`
- `revealed_attributes`
- current-topic `last_tool_results`

Suggested fields to keep:

- `recent_objects`
- thread continuity summary
- older route history

This prevents the agent from becoming fully amnesic while still ending the
current conversational topic.

## Revealed Attributes

`revealed_attributes` should be treated as a first-class response-memory field.

Examples:

- `identity`
- `applications`
- `species_reactivity`
- `validation`
- `workflow`
- `timeline`

This enables:

- better `ELABORATE` behavior
- less repetition
- more deliberate layered disclosure

The memory layer does not decide which attributes to reveal next, but it should
store which ones have already been revealed.

## Clarification Priority

Pending clarification must be treated as stronger than generic fallback
continuity.

That means:

- if `pending_clarification_type = product_selection`
  - a reply like `32122` should be interpreted through that lens first
- if `pending_clarification_type = identifier_type`
  - a reply like `catalog number` should resolve that clarification state first

This is why clarification memory must remain typed.

## Ideal Directory Shape

Ignoring the current repo layout, the ideal shape would be:

```text
src/memory/
  __init__.py
  models.py
  store.py
  thread_memory.py
  object_memory.py
  clarification_memory.py
  response_memory.py
  adapters/
    redis_store.py
```

## Module Responsibilities

### `models.py`

Defines:

- `StatefulAnchors`
- `MemorySnapshot`
- `MemoryUpdate`
- `ThreadMemory`
- `ObjectMemory`
- `ClarificationMemory`
- `ResponseMemory`

### `store.py`

Defines the memory read/write interface.

Responsibilities:

- load snapshot
- persist snapshot
- apply updates

### `thread_memory.py`

Handles high-level thread continuity fields.

### `object_memory.py`

Handles:

- active object
- recent objects
- candidate object sets

### `clarification_memory.py`

Handles:

- pending clarification type
- pending candidate options
- pending route resumption

### `response_memory.py`

Handles:

- revealed attributes
- last tool results
- response continuity state

### `adapters/redis_store.py`

Handles Redis persistence.

Important:

- the adapter should only persist and retrieve typed memory models
- it should not embed routing or object-resolution logic

## Current Codebase Mapping

The current codebase already contains memory-like behavior in:

- [session_store.py](/Users/promab/anaconda_projects/email_agent/src/memory/session_store.py)
- [routing_state_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/routing_state_service.py)
- [payload_schema.py](/Users/promab/anaconda_projects/email_agent/src/schemas/payload_schema.py)
- [route_decision_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_decision_service.py)

Current issue:

- memory concerns are spread across payload schema, route state, and response behavior
- not all state classes are clearly separated
- active object state and clarification state are mixed too closely with routing state

The redesign should therefore:

- preserve the useful state fields
- separate them by state family
- expose typed anchors rather than loose dicts

## Migration Strategy

### Phase 1: Define Typed Memory Models

- define `MemorySnapshot`
- define `MemoryUpdate`
- define `StatefulAnchors`

### Phase 2: Separate State Families

- split current persisted payload into:
  - thread memory
  - object memory
  - clarification memory
  - response memory

### Phase 3: Make Ingestion Consume Anchors Only

- ingestion should stop reading mixed session payload directly
- ingestion should receive typed `stateful_anchors`

### Phase 4: Make Downstream Layers Stop Reading Storage Directly

- `objects`
- `routing`
- `tools`
- `response`

should all consume typed contracts instead of raw store payloads

### Phase 5: Add Soft Reset Semantics

- implement object/topic-level clearing
- avoid full thread memory resets by default

## Testing Strategy

The memory layer should be validated at four levels:

### 1. Snapshot Integrity Tests

Test whether a saved `MemorySnapshot` can be reloaded without shape drift.

### 2. Update Application Tests

Test whether `MemoryUpdate` operations correctly:

- set active object
- clear pending clarification
- append recent objects
- mark revealed attributes

### 3. Anchor Conversion Tests

Test whether memory state converts correctly into `stateful_anchors` for ingestion.

### 4. Continuity Behavior Tests

Test whether:

- clarification replies
- follow-ups
- soft resets
- elaborate turns

all behave correctly when memory is present.

## Summary

The memory layer should store only state that later turns can actually use.

Its job is simple:

1. preserve typed continuity state
2. expose `stateful_anchors`
3. accept explicit updates
4. support soft reset without full amnesia

That is what will make:

- follow-up interpretation cleaner
- clarification handling more reliable
- object continuity less fragile
- response layering less repetitive
