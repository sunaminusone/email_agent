# Routing Redesign

## Goal

Redesign routing so that it no longer behaves like a branch selector for parallel systems such as:

- catalog route
- RAG route
- pricing route
- workflow route
- operational route

Instead, routing should become a layered decision stack that answers four questions in order:

1. what object is in play?
2. what interaction is the user making?
3. what information modality is needed?
4. what tools should be executed?

## Boundary Contract

Routing sits after `objects`, not above it.

That means:

- `ingestion` produces `IngestionBundle`
- `objects` consumes `IngestionBundle` and produces `ResolvedObjectState`
- `routing` consumes `ResolvedObjectState` and decides what to do next

So routing should not directly:

- call object extraction
- call object resolution
- read raw parser output
- re-read Redis or session state to rediscover objects

Its job starts only after object state has already been resolved.

## Why The Current Routing Feels Wrong

The current routing model is still too path-oriented.

It often behaves as if the system must choose one world:

- "go to catalog"
- "go to technical RAG"
- "go to operational lookup"

That creates several problems:

- catalog and RAG feel like parallel systems instead of tools
- route names carry too much business logic
- `selection.py` and route preconditions end up doing orchestration work
- it becomes difficult to support hybrid answers cleanly

## Router Becomes An Orchestrator

In the redesigned architecture, the router is no longer a branch selector.

It becomes a task orchestrator.

That means its job is no longer:

- "pick one business path"

It becomes:

- "coordinate dialogue understanding, modality selection, tool usage, and fallback behavior into one execution plan"

In practical terms, the orchestrator is responsible for five things:

1. sequencing
2. tool selection
3. context injection
4. fallback control
5. result assembly policy

### 1. Sequencing

The orchestrator defines execution order across modules.

It should coordinate the flow like this:

1. receive resolved object state
2. classify dialogue act
3. choose modality
4. choose tools
5. execute tools
6. assemble tool results
7. synthesize the answer

The orchestrator should not embed lookup logic itself.

It should only decide who runs next.

### 2. Tool Selection

This is the orchestrator's most important decision power.

It should select tools based on:

- object type
- dialogue act
- modality

Examples:

- `product + inquiry + hybrid`
  - `catalog_lookup_tool`
  - `technical_rag_tool`
- `service + inquiry + unstructured_retrieval`
  - `technical_rag_tool`
- `order + inquiry + external_api`
  - `order_lookup_tool`
  - optionally `shipping_lookup_tool`

Important rule:

- the orchestrator decides **which tools to call**
- each tool decides **how to execute its internal retrieval logic**

This keeps orchestration out of tool internals.

### 3. Context Injection

The orchestrator must pass resolved constraints forward.

Examples:

- if object resolution locks `MA5-11515`, then any downstream technical retrieval should receive that resolved identifier or product scope
- if the active object is a specific service, technical retrieval should be scoped to that service
- if clarification is active, the candidate set should be injected into the next-turn interpretation logic

This is one of the most important changes in the new design:

- tools should not rediscover context on their own if the orchestrator already knows it
- routing should inject resolved object constraints, not rediscover them by re-reading upstream state

### 4. Fallback Control

The orchestrator should decide what happens when the preferred path fails.

Examples:

- if object resolution remains ambiguous, do not execute product tools yet; trigger clarification
- if a rewrite or grounded LLM phrasing step fails, fall back to deterministic rendering
- if a tool result is incomplete, decide whether to continue with another tool, clarify, or hand off

Fallback control should live in orchestration rather than being scattered across tools and renderers.

### 5. Result Assembly Policy

The orchestrator should also decide how multiple tool results are combined before response synthesis.

This becomes especially important for hybrid turns.

Examples:

- `product + hybrid`
  - catalog facts become the primary answer spine
  - technical/doc retrieval becomes support material
- `service + hybrid`
  - technical RAG may provide the main answer
  - document lookup may provide supplementary deliverables or references

The orchestrator therefore needs a small policy for:

- which tool result is primary
- which tool results are supporting
- whether results should be merged, summarized, or clarified

Without this, hybrid execution becomes ad hoc and inconsistent.

## New Routing Principle

Routing should not begin with:

- "Which route should I enter?"

It should begin with:

- "What is the user talking about?"
- "What is the user trying to do?"
- "What kind of information is needed?"

Only after those are answered should the system choose tools.

## The New Routing Stack

Routing should consume:

- `ResolvedObjectState`
- `DialogueActResult`
- optional modality hints derived from the resolved object and current turn

Routing should not consume:

- raw parser output
- direct session storage
- direct registry lookups
- ad hoc object candidates that bypass the objects layer

### Layer 1: Object Routing

This layer does not perform extraction or resolution itself.

Instead, it consumes the already-resolved object state and decides how routing
should interpret that state for execution planning.

Possible primary objects:

- `product`
- `service`
- `order`
- `invoice`
- `shipment`
- `document`
- `customer`
- `scientific_target`

This layer should output:

- `primary_object`
- `secondary_objects`
- `ambiguous_objects`
- `active_object`

It should not decide the final response.

### Layer 2: Interaction Routing

This layer determines the dialogue act.

MVP acts:

- `INQUIRY`
- `SELECTION`
- `ACKNOWLEDGE`
- `TERMINATE`
- `ELABORATE`
- `UNKNOWN`

This layer answers:

- is the user asking a new question?
- selecting from candidates?
- acknowledging?
- stopping?
- requesting more detail?

It should not decide whether catalog or RAG is used.

### Layer 3: Modality Routing

This layer determines what kind of information is needed for the current object.

Possible modalities:

- `structured_lookup`
- `unstructured_retrieval`
- `external_api`
- `hybrid`

Examples:

- `product + structured_lookup`
  - catalog facts
  - application
  - species
- `product + hybrid`
  - catalog facts + datasheet/protocol/validation text
- `service + unstructured_retrieval`
  - workflow
  - plan
  - models
  - validation
- `order + external_api`
  - order status
  - shipping data

This layer should not execute tools itself.

### Layer 4: Tool Routing

This layer selects the actual tools.

Recommended tool vocabulary:

- `catalog_lookup_tool`
- `technical_rag_tool`
- `document_lookup_tool`
- `pricing_lookup_tool`
- `order_lookup_tool`
- `shipping_lookup_tool`
- `invoice_lookup_tool`

Examples:

- `product + inquiry + structured_lookup`
  - `catalog_lookup_tool`
- `product + inquiry + hybrid`
  - `catalog_lookup_tool`
  - `technical_rag_tool`
- `service + inquiry + unstructured_retrieval`
  - `technical_rag_tool`
- `product + selection`
  - update object state first
  - then continue to normal inquiry routing

## Top-Level Route Surface Should Shrink

The top-level route layer should become much smaller.

Recommended top-level route outcomes:

- `clarification`
- `execution`
- `handoff`

That means:

- if the object is ambiguous, route to `clarification`
- if the object and act are actionable, route to `execution`
- if the case exceeds system confidence or policy, route to `handoff`

The detailed business decision should move inside `execution`.

## Recommended Execution Intent Shape

Routing should produce one compact execution intent object, for example:

```python
{
    "primary_object": {
        "object_type": "product",
        "canonical_value": "Rabbit Polyclonal antibody to MSH2",
        "identifier": "P06329",
        "identifier_type": "catalog_number",
    },
    "dialogue_act": "INQUIRY",
    "modality": "structured_lookup",
    "selected_tools": ["catalog_lookup_tool"],
    "needs_clarification": False,
    "handoff_required": False,
}
```

This is the main architectural change:

- route does not directly answer
- route does not directly embody one business world
- route emits a plan-ready intent

## Clarification Becomes Cleaner

Clarification should happen only for a few explicit reasons:

- object ambiguity
- missing referential scope
- missing required identifier
- incomplete operational reference

It should not be used as a catch-all fallback for uncertain routing.

## Hybrid Routing Becomes First-Class

This design makes hybrid answers much easier.

Examples:

### Product Technical Question

User asks:

- `What applications is this antibody validated for?`

Route stack:

- object: `product`
- act: `INQUIRY`
- modality: `hybrid`
- tools:
  - `catalog_lookup_tool`
  - `technical_rag_tool`

### Service Plan Follow-Up

User asks:

- `What is your service plan?`

Route stack:

- object: `service`
- act: `INQUIRY`
- modality: `unstructured_retrieval`
- tools:
  - `technical_rag_tool`

### Order Tracking

User asks:

- `Where is my order 54321?`

Route stack:

- object: `order`
- act: `INQUIRY`
- modality: `external_api`
- tools:
  - `order_lookup_tool`
  - `shipping_lookup_tool`

## What This Means For Current Modules

### `route_preconditions.py`

Should become narrower.

Its job should be:

- block invalid execution
- trigger clarification when required
- avoid unsafe fallback

It should not continue to absorb object resolution and business-path logic.

### `selector.py`

Should move closer to tool selection rather than route naming.

It should select tools based on:

- resolved object
- dialogue act
- modality

not just route heuristics.

### `selection.py`

Should no longer carry hidden routing behavior.

It should become:

- candidate retrieval
- candidate scoring
- ambiguity grouping

not orchestration.

## Migration Plan

### Phase 1

Keep current route names, but internally add the layered routing outputs:

- object
- act
- modality
- tools

### Phase 2

Make `execution` the main path and reduce business-specific route branching.

### Phase 3

Refactor existing responders and execution plans to consume the layered routing output directly.

### Phase 4

Retire old route-centric assumptions where catalog and RAG are treated like separate worlds.

## Summary

The new routing system should be:

- object-centric
- act-aware
- modality-aware
- tool-oriented

In short:

1. resolve object
2. resolve act
3. resolve modality
4. select tools
5. execute
6. respond

That is the cleanest way to make the system feel like:

- one agent
- multiple tools
- coherent multi-turn behavior

instead of a set of parallel subsystems.
