# Implementation Roadmap

## Goal

This roadmap translates the current architecture documents into a practical
refactor sequence.

It answers one question:

> In what order should the codebase be changed so the new architecture lands cleanly without forcing a full rewrite?

## Guiding Strategy

The refactor should follow four high-level rules:

1. define contracts before moving logic
2. wrap existing modules before replacing them
3. move one architectural boundary at a time
4. keep current production behavior working while new layers are introduced

This is not a "big bang" rewrite.

It is a staged migration.

## Target Architecture Chain

The target runtime chain is:

1. `memory`
2. `ingestion`
3. `objects`
4. `routing`
5. `tools`
6. `execution`
7. `response`

The implementation order should broadly follow the same sequence, but with one
important adjustment:

- start by stabilizing schemas and boundaries
- only then move runtime behavior behind those boundaries

## Phase 0: Freeze Vocabulary And Entry Contracts

### Objective

Make sure all later work uses the same architectural names and the same core
contracts.

### Deliverables

- keep the current design docs as the source of truth
- standardize names around:
  - `IngestionBundle`
  - `ResolvedObjectState`
  - `DialogueActResult`
  - `ModalityDecision`
  - `ExecutionIntent`
  - `ToolRequest`
  - `ToolResult`
  - `ExecutionPlan`
  - `ExecutionRun`
  - `ComposedResponse`

### Current Status

Mostly done in:

- [ARCHITECTURE_READING_ORDER.md](/Users/promab/anaconda_projects/email_agent/docs/ARCHITECTURE_READING_ORDER.md)
- [INGESTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_LAYER_DESIGN.md)
- [OBJECTS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/OBJECTS_LAYER_DESIGN.md)
- [ROUTING_REDESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_REDESIGN.md)

## Phase 1: Define Core Schemas Only

### Objective

Introduce the new contracts in code without changing business logic yet.

### Recommended First Schemas

1. ingestion contracts
   - `IngestionBundle`
   - `EntitySpan`
   - `StatefulAnchors`
2. object contracts
   - `ObjectCandidate`
   - `AmbiguousObjectSet`
   - `ResolvedObjectState`
3. routing contracts
   - `DialogueActResult`
   - `ModalityDecision`
   - `ExecutionIntent`
4. tool contracts
   - `ToolRequest`
   - `ToolResult`
   - `ToolCapability`
5. execution contracts
   - `PlannedToolCall`
   - `ExecutionPlan`
   - `ExecutedToolCall`
   - `ExecutionRun`
6. response contracts
   - `ResponseInput`
   - `ResponsePlan`
   - `ComposedResponse`

### Important Rule

Do not wire all of them into runtime immediately.

This phase is only about making the contracts available and testable.

## Phase 2: Build Ingestion Boundary

### Objective

Create the new ingestion layer as a stable front door without physically moving
all old parser-related files.

### New Modules To Add

- `src/ingestion/models.py`
- `src/ingestion/pipeline.py`
- `src/ingestion/normalizers.py`
- `src/ingestion/parser_adapter.py`
- `src/ingestion/signal_refinement.py`
- `src/ingestion/deterministic_signals.py`
- `src/ingestion/reference_signals.py`
- `src/ingestion/stateful_anchors.py`

### Existing Modules To Wrap

- [preprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/preprocess.py)
- [chain.py](/Users/promab/anaconda_projects/email_agent/src/parser/chain.py)
- [postprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/postprocess.py)
- [service.py](/Users/promab/anaconda_projects/email_agent/src/parser/service.py)
- [intent_resolution.py](/Users/promab/anaconda_projects/email_agent/src/parser/intent_resolution.py)
- [identifier_extraction.py](/Users/promab/anaconda_projects/email_agent/src/strategies/identifier_extraction.py)
- [reference_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/reference_resolution_service.py)

### Migration Rule

Do not move these files physically at first.

Instead:

- keep them where they are
- adapt them behind the ingestion boundary

### Exit Condition

One call should be able to produce a complete `IngestionBundle`.

## Phase 3: Build Objects Layer

### Objective

Move object extraction and object resolution out of scattered helpers and into
one dedicated layer.

### New Modules To Add

- `src/objects/models.py`
- `src/objects/extraction.py`
- `src/objects/resolution.py`
- `src/objects/normalizers.py`
- `src/objects/extractors/product_extractor.py`
- `src/objects/extractors/service_extractor.py`
- `src/objects/extractors/operational_extractor.py`
- `src/objects/extractors/context_extractor.py`

### Existing Modules To Shrink Or Wrap

- [service_registry.py](/Users/promab/anaconda_projects/email_agent/src/conversation/service_registry.py)
- [product_registry.py](/Users/promab/anaconda_projects/email_agent/src/catalog/product_registry.py)
- [context_scope.py](/Users/promab/anaconda_projects/email_agent/src/conversation/context_scope.py)
- [payload_builders.py](/Users/promab/anaconda_projects/email_agent/src/conversation/payload_builders.py)

### Architectural Rule

`objects` should consume:

- `IngestionBundle`

and nothing else directly.

History must enter only through:

- `stateful_anchors`

### Exit Condition

One call should be able to produce a complete `ResolvedObjectState`.

## Phase 4: Narrow Current Selection Logic

### Objective

Shrink `selection.py` so it becomes candidate retrieval only.

### Modules To Refactor

- [selection.py](/Users/promab/anaconda_projects/email_agent/src/catalog/selection.py)
- [normalization.py](/Users/promab/anaconda_projects/email_agent/src/catalog/normalization.py)
- [shared.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/shared.py)
- [ranking.py](/Users/promab/anaconda_projects/email_agent/src/catalog/ranking.py)

### Target Responsibility

`selection.py` should answer:

> Given an object retrieval signal, what are the best candidate objects?

It should no longer decide:

- modality
- response behavior
- broad business strategy

### Exit Condition

Catalog selection behaves like a narrow object candidate service, not a hidden
orchestrator.

## Phase 5: Build Routing Contracts And Adapt Route Logic

### Objective

Turn routing into a pure decision layer that consumes object state.

### New Or Refactored Modules

- `src/decision/dialogue_act.py`
- `src/decision/modality.py`
- `src/decision/tool_selection.py`
- [route_decision_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_decision_service.py)
- [route_preconditions.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_preconditions.py)

### Architectural Rule

Routing should consume:

- `ResolvedObjectState`

Routing should internally resolve:

- `DialogueActResult`
- `ModalityDecision`

It should emit:

- `ExecutionIntent`

### Keep For Compatibility

Current route names can stay temporarily, but should become outputs or labels on
top of the new routing structure rather than the architecture itself.

### Exit Condition

Routing no longer redoes object logic and no longer behaves like "choose a
world".

## Phase 6: Standardize Tools

### Objective

Wrap existing lookup and retrieval capabilities behind shared tool contracts.

### Existing Modules To Adapt

- [catalog_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/catalog_tools.py)
- [rag_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/rag_tools.py)
- [order_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/order_lookup.py)
- [invoice_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/invoice_lookup.py)
- [shipping_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/shipping_lookup.py)

### New Shared Contracts

- `ToolRequest`
- `ToolResult`
- `ToolCapability`

### Exit Condition

Tools can be selected and executed uniformly, regardless of whether they talk to
catalog data, RAG, or external systems.

## Phase 7: Build Execution Layer

### Objective

Introduce explicit planning and execution around selected tools.

### Existing Modules To Adapt

- [planner_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/planner_service.py)
- [executor_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/executor_service.py)
- [plan_schema.py](/Users/promab/anaconda_projects/email_agent/src/schemas/plan_schema.py)

### Target Chain

- `ExecutionIntent`
  -> `ExecutionPlan`
  -> tool calls
  -> `ExecutionRun`

### Key Work

- define primary vs supporting tool roles
- define merge policy
- support single, sequential, and parallel execution

### Exit Condition

Execution becomes the only layer that coordinates multiple tool runs.

## Phase 8: Split And Stabilize Memory

### Objective

Separate memory state families and stop leaking mixed payloads into business
logic.

### Existing Modules To Adapt

- [session_store.py](/Users/promab/anaconda_projects/email_agent/src/memory/session_store.py)
- [payload_schema.py](/Users/promab/anaconda_projects/email_agent/src/schemas/payload_schema.py)
- [routing_state_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/routing_state_service.py)

### Target Memory Families

- `thread_memory`
- `object_memory`
- `clarification_memory`
- `response_memory`

### Key Work

- define `MemorySnapshot`
- define `MemoryUpdate`
- derive `stateful_anchors` cleanly for ingestion
- add soft reset semantics

### Exit Condition

Downstream layers stop reading raw session payloads directly.

## Phase 9: Rebuild Response Around Execution Output

### Objective

Make response generation consume `ExecutionRun` rather than scattered upstream
state.

### Existing Modules To Adapt

- [response/chain.py](/Users/promab/anaconda_projects/email_agent/src/response/chain.py)
- [response/content/blocks.py](/Users/promab/anaconda_projects/email_agent/src/response/content/blocks.py)
- [product_renderer.py](/Users/promab/anaconda_projects/email_agent/src/responders/renderers/product_renderer.py)
- [technical_renderer.py](/Users/promab/anaconda_projects/email_agent/src/responders/renderers/technical_renderer.py)
- [document_renderer.py](/Users/promab/anaconda_projects/email_agent/src/responders/renderers/document_renderer.py)

### Target Chain

- `ExecutionRun`
  -> `ResponsePlan`
  -> deterministic content blocks
  -> optional constrained rewrite
  -> `ComposedResponse`

### Exit Condition

The response layer becomes grounded, unified, and execution-driven.

## Phase 10: Eval And Observability

### Objective

Add the measurement and tracing needed to trust the migration.

### Required Eval Tracks

- ingestion signal eval
- object resolution eval
- routing eval
- tool selection eval
- execution merge eval
- response quality eval

### Required Observability

- execution trace by layer
- tool request/result visibility
- retrieval debug visibility
- clarification-state traceability

### Exit Condition

The new architecture is not just implemented, but measurable.

## Suggested Weekly Grouping

If this work is done incrementally, a practical grouping is:

### Group A

- Phase 1
- Phase 2

### Group B

- Phase 3
- Phase 4

### Group C

- Phase 5
- Phase 6

### Group D

- Phase 7
- Phase 8

### Group E

- Phase 9
- Phase 10

This keeps the system stable while each new boundary lands.

## Recommended Starting Point

If you want the first real implementation step after design, start here:

1. define the new contracts in code
2. build the ingestion boundary
3. build object extraction and resolution

That is the smallest sequence that creates a new spine for the rest of the
system.

## Summary

The roadmap should not be:

- rewrite everything

It should be:

1. define contracts
2. create boundaries
3. wrap old modules
4. shift responsibilities upward or downward one layer at a time
5. keep measuring as the system changes

That is the safest way to move from the current mixed architecture to the new
object-centric design.
