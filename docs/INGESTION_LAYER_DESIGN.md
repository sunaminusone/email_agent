# Ingestion Layer Design

## Goal

The ingestion layer is the structured entrypoint for every user turn.

Its job is not to resolve objects or choose tools. Its job is to emit one clean,
trustworthy signal bundle that answers:

> What evidence do we have about this turn before object resolution begins?

In short:

- `ingestion` gathers evidence
- `objects` interprets that evidence
- `routing` decides what to do with the resolved objects

## Position In The Stack

The intended execution order is:

1. `ingestion`
2. `objects`
3. `routing`
4. `tools`
5. `execution`
6. `response`

The ingestion layer therefore sits before:

- object extraction
- object resolution
- dialogue-act routing
- tool selection
- response synthesis

## Boundary

### In Scope

The ingestion layer should:

1. normalize the turn
2. run the parser
3. refine parser output
4. extract deterministic identifiers and context clues
5. detect referential language
6. expose prior-state anchors without treating them as fresh evidence
7. emit one unified `IngestionBundle`

### Out Of Scope

The ingestion layer should not:

- decide the primary object
- collapse ambiguity
- choose tools
- choose retrieval modality
- select a response strategy
- generate the final answer

## Why This Layer Must Be Explicit

The current codebase already contains most ingestion logic, but it is scattered
across parser preprocessing, parser invocation, parser cleanup, identifier
extraction, referential handling, and session carry-over.

That creates four recurring problems:

1. downstream layers have to rediscover the same signals
2. parser-era logic leaks into routing and selection
3. deterministic and parser signals do not share one contract
4. stale state can be confused with fresh user evidence

So this refactor should begin as a unification pass, not as a rewrite.

## Canonical Output

The ingestion layer should emit one bundle with three top-level sections:

```python
{
    "turn_core": {...},
    "turn_signals": {...},
    "stateful_anchors": {...},
}
```

This separation is intentional:

- `turn_core` is metadata about the turn itself
- `turn_signals` are derived only from the current user turn
- `stateful_anchors` are carried-over constraints from prior conversation state

## Output Contract

### 1. `turn_core`

```python
{
    "thread_id": str,
    "raw_query": str,
    "normalized_query": str,
    "language": str,
    "channel": str,
}
```

### 2. `turn_signals`

This section contains only current-turn evidence. It should be split into:

- `parser_signals`
- `deterministic_signals`
- `reference_signals`
- `attachment_signals`

### 3. `stateful_anchors`

This section contains prior-state constraints only. Example:

```python
{
    "active_route": "commercial_agent",
    "active_entity_kind": {
        "value": "product",
        "recency": "CONTEXTUAL",
        "source_type": "stateful_anchor",
    },
    "pending_clarification_field": "product_selection",
}
```

These are not current-turn facts. They are historical anchors.

## Signal Families

### Parser Signals

Parser signals should preserve the important structured meaning from the current
parser contract without blindly passing the raw parser object downstream.

Recommended content:

```python
{
    "context": {...},
    "request_flags": {...},
    "constraints": {...},
    "open_slots": {...},
    "retrieval_hints": {...},
    "tool_hints": {...},
    "missing_information": [...],
    "entities": {...},
}
```

### Deterministic Signals

These are strong non-LLM signals extracted directly from the current turn.

Recommended content:

```python
{
    "catalog_numbers": [...],
    "order_numbers": [...],
    "invoice_numbers": [...],
    "ambiguous_identifiers": [...],
    "document_types": [...],
    "product_context": bool,
    "service_context": bool,
    "invoice_context": bool,
    "order_context": bool,
    "documentation_context": bool,
    "pricing_context": bool,
    "timeline_context": bool,
    "technical_context": bool,
}
```

### Reference Signals

Reference signals should model referential behavior, not resolve the target
entity yet.

Recommended content:

```python
{
    "is_context_dependent": bool,
    "reference_mode": "active" | "other" | "first" | "second" | "previous" | "all" | "none",
    "referenced_prior_context": {
        "value": str,
        "recency": "CURRENT_TURN",
        "source_type": "parser",
    },
    "attribute_constraints": [
        {
            "attribute": str,
            "operator": str,
            "value": str,
            "recency": "CURRENT_TURN",
            "source_type": "parser" | "deterministic",
        }
    ],
    "requires_active_context_for_safe_resolution": bool,
}
```

Examples of `attribute_constraints`:

- `the human antibody`
- `the 100ul one`
- `the rabbit monoclonal one`
- `the IHC-validated one`

These should be treated as filters over an existing candidate set, not as new
primary entities.

### Attachment Signals

```python
{
    "has_attachments": bool,
    "attachment_count": int,
    "attachment_names": list[str],
    "attachment_types": list[str],
    "attachment_ids": list[str],
    "storage_uris": list[str],
}
```

Names and file types are useful for intent shaping, but they are not enough for
tool execution. The ingestion contract should therefore preserve physical
attachment pointers as first-class fields.

Recommended interpretation:

- `attachment_names` and `attachment_types`
  - support UX, routing, and attachment-aware prompting
- `attachment_ids` and `storage_uris`
  - support deterministic downstream file access by document tools and RAG

### Stateful Anchors

Stateful anchors expose safe prior-state constraints without pretending they are
new evidence.

Recommended content:

```python
{
    "active_route": str,
    "active_business_line": {
        "value": str,
        "recency": "CONTEXTUAL",
        "source_type": "stateful_anchor",
    },
    "active_entity_kind": {
        "value": str,
        "recency": "CONTEXTUAL",
        "source_type": "stateful_anchor",
    },
    "pending_clarification_field": str,
    "pending_candidate_options": list[str],
    "pending_identifier": str,
}
```

## Entity Fingerprints

Entity-like fields should not remain as `list[str]`. They should preserve raw
surface form and span information via a structured fingerprint.

Recommended model:

```python
{
    "text": str,
    "raw": str,
    "normalized_value": str | None,
    "start": int,
    "end": int,
    "recency": "CURRENT_TURN" | "CONTEXTUAL",
    "source_type": "parser" | "deterministic" | "stateful_anchor",
}
```

Suggested name:

- `EntitySpan`

This is especially useful for:

- `product_names`
- `service_names`
- `targets`
- `catalog_numbers`
- `order_numbers`
- `invoice_numbers`

Why this matters:

1. object resolution can compare two surface forms more safely
2. ambiguity handling can preserve the user's original wording
3. grounded response synthesis can quote what the user actually said
4. debug and UI layers can inspect where the entity came from

### Canonicalization Placement

The ingestion layer should preserve both:

- the user's original surface form
- the system's normalized lookup form

So `EntitySpan` should carry:

- `raw`
  - what the user literally wrote
- `text`
  - the cleaned span used inside ingestion
- `normalized_value`
  - the canonicalized value produced by refinement or registry-backed normalization

Example:

```python
{
    "text": "NPM1",
    "raw": "npm-1",
    "normalized_value": "Mouse Monoclonal antibody to Nucleophosmin",
    "start": 12,
    "end": 17,
    "recency": "CURRENT_TURN",
    "source_type": "parser",
}
```

This lets downstream layers:

- preserve grounded user phrasing in the response layer
- use normalized values for exact lookup and object matching
- avoid conflating surface form with canonical form

## Recency And Provenance

The ingestion contract must explicitly mark:

- whether a signal is `CURRENT_TURN` or `CONTEXTUAL`
- where it came from

Recommended `source_type` values:

- `deterministic`
- `parser`
- `attachment`
- `stateful_anchor`

Example:

- `catalog_number = 32122` extracted from the current user turn
  - `recency = CURRENT_TURN`
  - `source_type = deterministic`

- `catalog_number = 32122` carried over from a prior selected candidate
  - `recency = CONTEXTUAL`
  - `source_type = stateful_anchor`

These must not be treated as equally strong.

## Priority Rules

The ingestion contract should make precedence explicit:

1. current-turn deterministic signals
2. current-turn parser signals
3. contextual stateful anchors

So:

- `CURRENT_TURN` beats `CONTEXTUAL`
- deterministic beats parser when both refer to the same kind of signal
- stateful anchors may assist interpretation, but may not override fresh evidence

## Ideal File Structure

Ignoring the current repo layout, the ingestion layer should ideally look like:

```text
src/ingestion/
  __init__.py
  models.py
  pipeline.py
  normalizers.py
  parser_adapter.py
  signal_refinement.py
  deterministic_signals.py
  reference_signals.py
  stateful_anchors.py
```

## Module Responsibilities

### `models.py`

Defines:

- `IngestionBundle`
- `ParserSignals`
- `DeterministicSignals`
- `ReferenceSignals`
- `StatefulAnchors`
- `AttachmentSignals`
- `EntitySpan`

Implementation rule:

- every list field should use `Field(default_factory=list)`
- nested models should prefer `Field(default_factory=...)`
- booleans should default to `False`
- avoid nullable containers where an empty iterable is semantically correct

### `pipeline.py`

The single public entrypoint. It should orchestrate:

1. turn normalization
2. parser invocation
3. parser signal refinement
4. deterministic extraction
5. reference signal extraction
6. stateful anchor extraction
7. final bundle assembly

### `normalizers.py`

Responsible only for turn-level normalization:

- query cleanup
- normalized query
- attachment normalization
- conversation-history normalization

This is not where product or service canonicalization should live.

### `parser_adapter.py`

Wraps the parser-facing components behind one stable interface:

- [preprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/preprocess.py)
- [chain.py](/Users/promab/anaconda_projects/email_agent/src/parser/chain.py)
- [service.py](/Users/promab/anaconda_projects/email_agent/src/parser/service.py)

### `signal_refinement.py`

Wraps refinement-stage logic from:

- [postprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/postprocess.py)
- [intent_resolution.py](/Users/promab/anaconda_projects/email_agent/src/parser/intent_resolution.py)

Refinement should be split into explicit stages:

- dedupe
- canonicalization
- intent correction
- request-flag correction
- attachment-related tool hints

### `deterministic_signals.py`

Wraps and extends:

- [identifier_extraction.py](/Users/promab/anaconda_projects/email_agent/src/strategies/identifier_extraction.py)

It should emit one deterministic signal object.

### `reference_signals.py`

Should absorb only the ingestion-time portion of:

- [reference_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/reference_resolution_service.py)

It should detect:

- context dependence
- referential phrases
- reference mode
- attribute-style filters on references
- whether active context is required for safe continuation

It should not resolve historical entities here.

### `stateful_anchors.py`

Should pull safe anchors from prior state:

- active route
- active entity
- active business line
- pending clarification
- selected candidate options

These are carried-over constraints only.

## Current File Review

This design is based on the current behavior of:

- [preprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/preprocess.py)
- [chain.py](/Users/promab/anaconda_projects/email_agent/src/parser/chain.py)
- [postprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/postprocess.py)
- [service.py](/Users/promab/anaconda_projects/email_agent/src/parser/service.py)
- [intent_resolution.py](/Users/promab/anaconda_projects/email_agent/src/parser/intent_resolution.py)
- [identifier_extraction.py](/Users/promab/anaconda_projects/email_agent/src/strategies/identifier_extraction.py)
- [reference_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/reference_resolution_service.py)

### What Each Current File Is Already Doing

#### [preprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/preprocess.py)

Current role:

- trims `user_query`
- serializes `conversation_history`
- serializes `attachments`
- preserves raw values in `_meta`

Interpretation:

- good parser-facing preprocessing
- too parser-specific to serve as the whole ingestion layer

#### [chain.py](/Users/promab/anaconda_projects/email_agent/src/parser/chain.py)

Current role:

- builds the parser pipeline
- invokes prompt + structured LLM
- runs parser postprocess

Interpretation:

- already acts like a mini ingestion pipeline
- but only for parser work

#### [postprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/postprocess.py)

Current role:

- dedupes parser outputs
- canonicalizes product and service names
- applies attachment-related file lookup hints
- upgrades some follow-up intent cases
- applies deterministic corrections

Interpretation:

- valuable ingestion cleanup
- currently mixes parser cleanup, canonicalization, and repair logic

#### [service.py](/Users/promab/anaconda_projects/email_agent/src/parser/service.py)

Current role:

- exposes `parse_user_input(...)`

Interpretation:

- good public parser adapter
- too narrow to serve as the full ingestion entrypoint

#### [intent_resolution.py](/Users/promab/anaconda_projects/email_agent/src/parser/intent_resolution.py)

Current role:

- upgrades `primary_intent` from flags and query text

Interpretation:

- deterministic intent refinement
- belongs in ingestion, not final routing

#### [identifier_extraction.py](/Users/promab/anaconda_projects/email_agent/src/strategies/identifier_extraction.py)

Current role:

- extracts catalog and order identifiers
- detects ambiguous numeric identifiers
- emits context booleans such as:
  - `product_context`
  - `invoice_context`
  - `order_context`
  - `documentation_context`
  - `pricing_context`
  - `timeline_context`
- detects document types

Interpretation:

- should become a first-class deterministic signal step inside ingestion

#### [reference_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/reference_resolution_service.py)

Current role:

- handles referential language such as:
  - `this one`
  - `that one`
  - `the other one`
  - `both of them`
- combines query, turn state, and session state

Interpretation:

- this file currently mixes two concerns:
  - ingestion-time reference detection
  - later stateful entity resolution

Only the first belongs in ingestion.

## Mapping From Current Files To New Ingestion Submodules

### Keep And Wrap First

- [preprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/preprocess.py)
  - wrap behind `parser_adapter.py`
- [chain.py](/Users/promab/anaconda_projects/email_agent/src/parser/chain.py)
  - wrap behind `parser_adapter.py`
- [service.py](/Users/promab/anaconda_projects/email_agent/src/parser/service.py)
  - keep as a thin compatibility wrapper first

### Keep But Conceptually Re-Home

- [postprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/postprocess.py)
  - re-home into `signal_refinement.py`
- [intent_resolution.py](/Users/promab/anaconda_projects/email_agent/src/parser/intent_resolution.py)
  - re-home into `signal_refinement.py`
- [identifier_extraction.py](/Users/promab/anaconda_projects/email_agent/src/strategies/identifier_extraction.py)
  - re-home into `deterministic_signals.py`
- [reference_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/reference_resolution_service.py)
  - split into:
    - ingestion-time reference detection -> `reference_signals.py`
    - later stateful entity resolution -> objects layer

## Recommended Refactor Slice

The safest first slice is:

1. define `IngestionBundle`
2. define `EntitySpan`
3. create `src/ingestion/pipeline.py`
4. wrap parser invocation behind `parser_adapter.py`
5. expose deterministic identifiers explicitly
6. expose reference signals explicitly
7. expose stateful anchors explicitly

Do not physically move every file on day one.

Instead:

- create the new ingestion boundary first
- keep old modules where they are
- adapt them behind the new interface

## Defensive Defaulting

The ingestion schema should be designed for sparse turns.

In real traffic, most turns will not populate most signal families. That means
the data model should prefer empty-but-iterable defaults over nullable
containers.

This is especially important for:

- `EntitySpan` collections
- `document_types`
- `attribute_constraints`
- `pending_candidate_options`
- attachment pointer fields

## Migration Order

### Phase 1: Build the contract

- create ingestion models
- create ingestion pipeline
- adapt parser and deterministic extraction into one bundle

### Phase 2: Split parser cleanup from signal refinement

- extract canonicalization and intent/flag repair into explicit refinement steps

### Phase 3: Split reference detection from stateful resolution

- keep raw referential detection in ingestion
- move actual entity selection by context to the objects layer

### Phase 4: Make agent input consume ingestion bundle

- [agent_input_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/agent_input_service.py)
  should stop stitching parser and hints manually
  and instead consume the unified ingestion output

## Summary

The ingestion layer should not become a giant parser wrapper.

It should become a clean, explicit pre-object pipeline that:

1. normalizes the turn
2. runs the parser
3. refines parser output
4. extracts deterministic signals
5. extracts reference signals
6. exposes stateful anchors
7. emits one ingestion bundle

That bundle then becomes the single upstream input to the objects layer.
