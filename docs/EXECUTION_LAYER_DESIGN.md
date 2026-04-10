# Execution Layer Design

## Goal

The execution layer should turn routing decisions into actual tool runs.

Its purpose is to answer one question:

> Given an `ExecutionIntent`, how should the system execute one or more tools and combine their results into one grounded run output?

In short:

- `routing` decides what should happen
- `execution` makes it runnable
- `tools` do the bounded work
- `response` turns the merged outputs into user-facing language

## Position In The Stack

The intended order is:

1. `ingestion`
2. `objects`
3. `routing`
4. `tools`
5. `execution`
6. `response`

This is a conceptual layer order, not the literal runtime call sequence.

More concretely:

1. `ingestion` emits `IngestionBundle`
2. `objects` emits `ResolvedObjectState`
3. `routing` emits `ExecutionIntent`
4. `execution` emits `ExecutionRun`
5. `response` consumes `ExecutionRun`

## Conceptual Layer vs Runtime Invocation

Execution should be understood in two complementary ways.

### Conceptual Layer Order

```text
routing
  -> tools
  -> execution
  -> response
```

In this view:

- tools are defined as reusable capabilities
- execution is the orchestration layer that depends on those capabilities

### Runtime Invocation Order

```text
routing
  -> execution
  -> tool calls
  -> response
```

In this view:

- execution receives `ExecutionIntent`
- execution creates `ExecutionPlan`
- execution invokes the planned tools
- execution merges their results into `ExecutionRun`

So execution does not sit "after tools" in the runtime sense.
It is the runtime layer that calls tools.

## Boundary

### In Scope

The execution layer should:

1. consume `ExecutionIntent`
2. generate an executable tool plan
3. decide whether tool calls should be single, sequential, or parallel
4. call the selected tools
5. capture per-tool execution metadata
6. merge tool results into one structured run output

### Out Of Scope

The execution layer should not:

- perform object extraction
- perform object resolution
- classify dialogue acts
- choose tools from scratch
- generate the final user-facing answer

## Core Design Principle

Execution is not routing.

Execution is not a tool.

Execution is the layer that turns:

- decision

into:

- bounded action

That means:

- `routing` selects tools
- `execution` plans and runs them
- `tools` do not orchestrate each other
- `response` does not need to understand individual tool internals

## Canonical Naming

The execution design should align to the architecture vocabulary:

- `IngestionBundle`
- `ResolvedObjectState`
- `DialogueActResult`
- `ModalityDecision`
- `ExecutionIntent`
- `ToolRequest`
- `ToolResult`
- `ExecutionPlan`
- `ExecutionRun`

Avoid mixing these with older route-centric names when the design really means
execution planning or execution output.

Interpretation note:

- `DialogueActResult` and `ModalityDecision` are usually carried inside `ExecutionIntent` and downstream `ToolRequest`
- execution should not treat them as a separate upstream layer boundary

## Core Contracts

### `PlannedToolCall`

Suggested shape:

```python
{
    "tool_name": str,
    "request": ToolRequest,
    "role": "primary" | "supporting",
    "priority": int,
    "can_run_in_parallel": bool,
    "depends_on": list[str],
}
```

Recommended interpretation:

- `tool_name`
  - the normalized tool capability to run
- `request`
  - the fully-scoped request injected into that tool
- `role`
  - whether this tool provides the primary answer spine or only supporting material
- `priority`
  - relative planning priority
- `can_run_in_parallel`
  - whether the call may be safely executed independently
- `depends_on`
  - upstream tool names whose outputs must exist first

### `ExecutionPlan`

Suggested shape:

```python
{
    "intent": ExecutionIntent,
    "planned_calls": list[PlannedToolCall],
    "execution_mode": "single" | "sequential" | "parallel",
    "merge_policy": str,
    "reason": str,
}
```

Recommended interpretation:

- `intent`
  - the routing output being executed
- `planned_calls`
  - the ordered or grouped tool calls
- `execution_mode`
  - the dominant run mode for this plan
- `merge_policy`
  - how tool results should be combined
- `reason`
  - a short explanation for why this plan shape was chosen

### `ExecutedToolCall`

Suggested shape:

```python
{
    "tool_name": str,
    "status": "ok" | "partial" | "empty" | "error",
    "request": ToolRequest,
    "result": ToolResult,
    "latency_ms": int,
    "error": str,
}
```

Recommended interpretation:

- `status`
  - execution status for this specific call
- `request`
  - the exact request that was sent
- `result`
  - the structured output returned by the tool
- `latency_ms`
  - per-tool timing
- `error`
  - the error message if execution failed

### `ExecutionRun`

Suggested shape:

```python
{
    "intent": ExecutionIntent,
    "plan": ExecutionPlan,
    "executed_calls": list[ExecutedToolCall],
    "merged_results": {
        "primary_facts": dict,
        "supporting_facts": dict,
        "snippets": list[dict],
        "artifacts": list[dict],
    },
    "final_status": "ok" | "partial" | "empty" | "error",
    "reason": str,
}
```

Recommended interpretation:

- `executed_calls`
  - the full trace of what was actually run
- `merged_results`
  - the normalized result bundle consumed by the response layer
- `final_status`
  - the aggregate execution outcome
- `reason`
  - summary explanation of the run outcome

## Execution Modes

The first implementation only needs three execution modes:

### 1. `single`

One tool is enough.

Examples:

- `product + structured_lookup`
- `order + external_api`
- `invoice + external_api`

### 2. `sequential`

One tool should run before another because the second tool depends on the first
tool's output or clarified constraints.

Examples:

- product lookup first, then product-scoped technical retrieval
- document pointer lookup first, then document retrieval

### 3. `parallel`

Two tools can run independently and then be merged.

Examples:

- order lookup and shipping lookup when both are independently keyed
- multiple document lookups for the same resolved product

## Merge Policy

The execution layer should own a clear merge policy so response synthesis does
not have to guess how tool outputs relate.

### Primary vs Supporting Results

Every multi-tool execution should identify:

- one primary result spine
- zero or more supporting result sets

Examples:

#### `product + hybrid`

- primary: `catalog_lookup_tool`
- supporting: `technical_rag_tool`

Expected merge behavior:

- structured catalog facts become `primary_facts`
- retrieved snippets become `snippets`
- any extra technical metadata becomes `supporting_facts`

#### `service + hybrid`

- primary: `technical_rag_tool`
- supporting: `document_lookup_tool`

Expected merge behavior:

- technical retrieval becomes the main answer body source
- document tool contributes artifacts or supporting detail

#### `order + external_api`

- primary: `order_lookup_tool`
- supporting: `shipping_lookup_tool`

Expected merge behavior:

- order facts remain primary
- shipping details become supporting operational facts

### Merge Rules

1. primary tool facts should be preserved without lossy re-interpretation
2. supporting tool outputs should not overwrite primary facts unless explicitly allowed
3. snippets and artifacts should be accumulated, not flattened away
4. empty supporting results should not fail an otherwise successful run
5. conflicting structured facts should be surfaced in debug metadata rather than silently replaced

## Planning Rules

### Rule 1: Execution must consume `ExecutionIntent`, not re-derive it

Execution should not:

- re-select tools
- re-resolve the primary object
- re-classify the dialogue act

It should trust the upstream decision contract.

### Rule 2: Tool requests must be fully constrained

Before calling a tool, execution should inject:

- the primary object
- secondary objects when relevant
- modality constraints
- any attribute constraints
- any attachment pointers or document pointers

The goal is to keep tools focused and bounded.

### Rule 3: Empty results are not always errors

Execution must distinguish:

- true tool failure
- valid empty result
- partial result

These should map to different run-level outcomes.

### Rule 4: Execution should be observable

Execution should always record:

- which tools were selected
- what requests they received
- which calls succeeded, failed, or returned empty
- how results were merged

This is critical for debugging hybrid behavior.

## Ideal Directory Shape

Ignoring the current repo layout, the ideal shape would be:

```text
src/execution/
  __init__.py
  contracts.py
  planner.py
  executor.py
  merger.py
  policies.py
```

## Module Responsibilities

### `contracts.py`

Defines:

- `PlannedToolCall`
- `ExecutionPlan`
- `ExecutedToolCall`
- `ExecutionRun`

### `planner.py`

Builds an `ExecutionPlan` from `ExecutionIntent`.

Responsibilities:

- create one or more `PlannedToolCall`
- choose execution mode
- assign primary vs supporting roles
- decide merge policy

### `executor.py`

Runs the plan.

Responsibilities:

- invoke tools
- capture timing and failures
- collect `ExecutedToolCall`

### `merger.py`

Combines tool results into one normalized result bundle.

Responsibilities:

- merge primary and supporting facts
- merge snippets
- merge artifacts
- preserve debug metadata

### `policies.py`

Holds reusable planning and merge policies.

Examples:

- `product_hybrid_merge_policy`
- `service_hybrid_merge_policy`
- `operational_parallel_merge_policy`

## Example Execution Flows

### Example 1: Product Structured Inquiry

Execution intent:

- object: `product`
- act: `INQUIRY`
- modality: `structured_lookup`
- tools: `catalog_lookup_tool`

Execution plan:

- one `PlannedToolCall`
- execution mode: `single`

Execution run:

- catalog facts returned
- merged into `primary_facts`

### Example 2: Product Hybrid Inquiry

Execution intent:

- object: `product`
- act: `INQUIRY`
- modality: `hybrid`
- tools:
  - `catalog_lookup_tool`
  - `technical_rag_tool`

Execution plan:

- run catalog first
- inject resolved product constraint into technical RAG
- merge catalog as primary and RAG as supporting

### Example 3: Order Tracking

Execution intent:

- object: `order`
- act: `INQUIRY`
- modality: `external_api`
- tools:
  - `order_lookup_tool`
  - optionally `shipping_lookup_tool`

Execution plan:

- sequential or parallel depending on available identifiers
- merge operational facts into one run output

## Current Codebase Mapping

The current codebase already contains execution-like behavior in:

- [planner_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/planner_service.py)
- [executor_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/executor_service.py)
- [plan_schema.py](/Users/promab/anaconda_projects/email_agent/src/schemas/plan_schema.py)

But the current structure is still partly route-centric and action-centric.

The redesign should therefore:

- preserve these implementation assets
- adapt them to object-centric tool execution
- standardize planning and run outputs around one execution contract

## Migration Strategy

### Phase 1: Define Execution Contracts

- define `PlannedToolCall`
- define `ExecutionPlan`
- define `ExecutedToolCall`
- define `ExecutionRun`

### Phase 2: Adapt Existing Planner/Executor Services

- wrap current planner behavior behind `ExecutionIntent -> ExecutionPlan`
- wrap current executor behavior behind `ExecutionPlan -> ExecutionRun`

### Phase 3: Standardize Tool Result Merging

- make primary vs supporting roles explicit
- standardize merged result payloads
- standardize final run status

### Phase 4: Connect Response Layer

- make response consume `ExecutionRun`
- stop letting response infer tool precedence on its own

## Testing Strategy

The execution layer should be validated at four levels:

### 1. Plan Construction Tests

Test whether an `ExecutionIntent` produces the expected:

- planned tools
- execution mode
- merge policy

### 2. Tool Run Trace Tests

Test whether executed calls capture:

- request
- status
- result
- latency
- error

### 3. Merge Policy Tests

Test whether primary and supporting results are merged correctly for:

- product hybrid
- service hybrid
- operational parallel flows

### 4. End-To-End Execution Tests

Test whether:

- `ExecutionIntent`
  -> `ExecutionPlan`
  -> `ExecutionRun`

stays stable across representative object and modality combinations.

## Summary

The execution layer should be the bridge between:

- decision

and:

- actual tool work

Its job is simple:

1. receive `ExecutionIntent`
2. build `ExecutionPlan`
3. run tools
4. merge `ToolResult`s
5. emit `ExecutionRun`

That separation is what will make:

- multi-tool behavior understandable
- hybrid answers easier to support
- response synthesis cleaner
- routing and tools stay narrow and well-scoped
