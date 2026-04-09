# Objects Layer Design

## Goal

Define the `objects` layer as the first major foundation of the new architecture.

This layer should answer one question clearly:

> What objects are present in the current turn, and what is their current resolution state?

It should do this before:

- routing
- tool selection
- execution planning
- response generation

## Boundary Contract

The `objects` layer should have one direct input only:

- `IngestionBundle`

This is a hard boundary, not a preference.

That means:

- `objects` should not directly consume raw parser output
- `objects` should not directly read Redis or session storage
- `objects` should not directly pull ad hoc state from routing helpers

Instead:

- all current-turn evidence must enter through `turn_signals`
- all historical state must enter through `stateful_anchors`

Internal dependencies are still allowed, but they are implementation details.

Examples of valid internal dependencies:

- product registry
- service registry
- object normalizers
- alias maps
- object-resolution helpers

So the intended contract is:

- direct input: `IngestionBundle`
- internal dependencies: registries and normalizers
- historical state path: `stateful_anchors` only

## Why This Layer Comes First

Many current system problems are downstream symptoms of one upstream issue:

- the system does not yet have one unified object model

That causes:

- product and service logic to drift apart
- `selection.py` to absorb orchestration responsibilities
- routing to behave like world-selection
- catalog and RAG to feel like parallel systems
- follow-up handling to be inconsistent

So the first real refactor should be the `objects` layer.

## Ideal Directory Shape

Ignoring the current repo layout, the ideal shape would be:

```text
src/objects/
  __init__.py
  models.py
  extraction.py
  resolution.py
  normalizers.py
  registries/
    __init__.py
    product_registry.py
    service_registry.py
  extractors/
    __init__.py
    product_extractor.py
    service_extractor.py
    operational_extractor.py
    context_extractor.py
```

## Module Responsibilities

### `models.py`

Defines the object-centric data model.

This file should be the schema anchor for the whole architecture.

Recommended models:

- `ResolvedObject`
- `ObjectCandidate`
- `ObjectBundle`
- `AmbiguousObjectSet`

### `extraction.py`

Thin orchestration entrypoint.

It should:

- consume one `IngestionBundle`
- call the individual extractors
- merge the returned candidates
- dedupe
- return one `ObjectBundle`

Important:

- this file should stay small
- it should not contain all extraction logic inline

### `resolution.py`

Resolves object state.

It should:

- choose `primary_object`
- retain `secondary_objects`
- retain `ambiguous_objects`
- reconcile current-turn objects with active/pending context

This file should be the object-state decision layer.

### `normalizers.py`

Shared text normalization for object values.

This should hold:

- case normalization
- whitespace normalization
- symbol normalization
- object-safe alias normalization helpers

This avoids scattering normalization across product/service modules.

### `registries/product_registry.py`

Structured product registry.

Responsibilities:

- canonical names
- alias maps
- ambiguity detection
- unique-vs-ambiguous resolution

### `registries/service_registry.py`

Structured service registry.

Responsibilities:

- canonical service names
- alias maps
- business line association

### `extractors/product_extractor.py`

Extract product-related objects from:

- `turn_signals.parser_signals.entities`
- `turn_signals.deterministic_signals`
- product registry matches derived from those signals

This extractor should output product candidates, not final routing decisions.

### `extractors/service_extractor.py`

Extract service-related objects from:

- `turn_signals.parser_signals.entities`
- `turn_signals.deterministic_signals`
- service registry canonicalization

### `extractors/operational_extractor.py`

Extract operational objects:

- order
- invoice
- shipment
- customer
- document request

using:

- `turn_signals.parser_signals`
- `turn_signals.deterministic_signals`

### `extractors/context_extractor.py`

Extract context-carried objects from:

- `stateful_anchors.active_*`
- `stateful_anchors.pending_clarification_*`
- `stateful_anchors.pending_candidate_options`

This lets current-turn extraction and historical context enter the same object model.
It must not read session state directly.

## Recommended Data Model

### `ObjectCandidate`

Suggested fields:

```python
{
    "object_type": "product" | "service" | "order" | "invoice" | "shipment" | "document" | "customer" | "scientific_target",
    "raw_value": str,
    "canonical_value": str,
    "identifier": str,
    "identifier_type": str,
    "confidence": float,
    "source": str,
    "metadata": dict,
    "is_ambiguous": bool,
}
```

### `ObjectBundle`

Suggested fields:

```python
{
    "ingestion_bundle": IngestionBundle,
    "current_candidates": list[ObjectCandidate],
    "context_candidates": list[ObjectCandidate],
    "all_candidates": list[ObjectCandidate],
}
```

### `ResolvedObjectState`

Suggested fields:

```python
{
    "primary_object": ObjectCandidate | None,
    "secondary_objects": list[ObjectCandidate],
    "ambiguous_objects": list[ObjectCandidate],
    "active_object": ObjectCandidate | None,
    "resolution_reason": str,
}
```

## Extraction Rules

### Rule 1: Extraction is additive

Do not collapse too early.

If the turn contains:

- one product
- one service
- one document request

all of those should remain visible at the extraction layer.

### Rule 2: Canonicalization is conservative

- unique alias -> canonicalize
- ambiguous alias -> preserve ambiguity
- unknown alias -> keep raw value

### Rule 3: Context extraction is not guessing

Context objects should only be added as candidates when:

- `stateful_anchors` clearly support reuse
- the turn is follow-up-like
- or pending clarification requires it

The objects layer must treat contextual candidates as weaker than current-turn
evidence unless later resolution rules explicitly allow reuse.

## Resolution Rules

### Rule 1: Current explicit object wins

If the current turn explicitly names a product or service:

- it beats prior active context

### Rule 2: Ambiguity must remain explicit

If alias lookup returns multiple product candidates:

- do not auto-select one
- preserve the ambiguity set

### Rule 3: Pending clarification can dominate interpretation

If the session is waiting for:

- `product_selection`
- `service_selection`
- `identifier_type`

then resolution must incorporate that state before any generic fallback.

### Rule 4: Active object is fallback only

The active object should be reused only when:

- current-turn object extraction is empty or weak
- the turn is context-dependent
- and no stronger current object exists

## What This Layer Should Not Do

The `objects` layer should not:

- choose tools
- choose response style
- choose catalog vs RAG directly
- generate final answers
- execute retrieval

Its job is object state, not orchestration.

## Integration Points

This layer should later feed:

- `routing/`
  - for object-aware orchestration
- `memory/`
  - for active object persistence
- `tools/`
  - as scoped constraints
- `response/`
  - as resolved scope/context metadata

## Migration Strategy

### Phase 1: Introduce object models and extraction entrypoint

Do this without deleting current code.

Initial adapters can wrap:

- `IngestionBundle`
- current registries
- existing normalization helpers

### Phase 2: Introduce explicit object resolution

Move logic out of:

- `context_scope.py`
- parts of `payload_builders.py`
- parts of `selection.py`

into a unified object-state layer.

### Phase 3: Make routing consume object state

Routing should stop inferring object semantics on its own.

It should receive:

- `primary_object`
- `secondary_objects`
- `ambiguous_objects`
- `active_object`

directly.

It should not re-read parser output or session state to rediscover those objects.

## Recommended First Refactor Slice

The safest first slice is:

1. define `ObjectCandidate` and `ResolvedObjectState`
2. build `product_extractor.py`
3. build `service_extractor.py`
4. build `context_extractor.py`
5. create `extraction.py` aggregator
6. add `resolution.py` with minimal primary/ambiguous selection

This gets the layer standing before broader routing refactors begin.

## Summary

The `objects` layer should become the system's foundation.

Its purpose is simple:

1. collect all object candidates
2. normalize them
3. preserve ambiguity
4. resolve current object state

Once that exists, the rest of the system can become much simpler:

- routing becomes orchestration
- tools become actual tools
- selection becomes smaller
- hybrid responses become cleaner

The most important rule is:

- `objects` consumes one contract: `IngestionBundle`
- registries are internal dependencies
- history enters only through `stateful_anchors`
