# Tools Layer Design

## Goal

The tools layer should define executable capabilities, not parallel business
worlds.

Its purpose is to answer one question:

> Given a resolved object, a dialogue act, and a modality decision, which concrete capability can retrieve or compute the required information?

In short:

- `routing` decides what should be done
- `tools` perform the work
- `execution` coordinates one or more tool runs

## Position In The Stack

The intended order is:

1. `ingestion`
2. `objects`
3. `routing`
4. `tools`
5. `execution`
6. `response`

This is a conceptual layer order, not the literal runtime call sequence.

In this conceptual view:

- `tools` is the capability layer
- `execution` is the orchestration layer that plans and invokes those capabilities

So the tools layer sits after:

- `IngestionBundle`
- `ResolvedObjectState`
- `ExecutionIntent`

and before:

- result assembly
- final grounded response synthesis

## Conceptual Layer vs Runtime Invocation

The tools layer is easy to misunderstand because it appears before `execution`
in the conceptual stack while still being invoked by execution at runtime.

Those two statements are both true.

### Conceptual Layer Order

```text
routing
  -> tools
  -> execution
  -> response
```

This means:

- routing defines what capabilities are needed
- tools define what capabilities exist
- execution knows how to run them

### Runtime Invocation Order

```text
routing
  -> execution
  -> tool calls
  -> response
```

This means:

- routing emits `ExecutionIntent`
- execution builds a plan and invokes tools
- tools do not self-start as an independent runtime stage

## Boundary

### In Scope

The tools layer should:

1. expose a stable capability surface
2. consume routing-injected constraints
3. execute retrieval, lookup, or external system calls
4. return structured tool results
5. surface execution metadata for downstream merging and debugging

### Out Of Scope

The tools layer should not:

- perform object extraction
- perform object resolution
- choose tools
- choose modality
- decide clarification vs execution vs handoff
- generate the final user-facing answer

## Design Principle

Tools should be modeled as:

- capability units

not as:

- route branches
- hidden orchestrators
- independent state machines

This means:

- `catalog_lookup_tool` is a tool
- `technical_rag_tool` is a tool
- `document_lookup_tool` is a tool
- `order_lookup_tool` is a tool
- `shipping_lookup_tool` is a tool
- `invoice_lookup_tool` is a tool

It should no longer feel like the system must choose one world such as:

- catalog world
- RAG world
- operational world

Instead, those are all tools available to the same agent.

## Boundary Contract

Tools should not consume raw user turns directly as their primary contract.

The direct tool inputs should be:

- `ExecutionIntent`
- tool-specific constraints extracted from that intent
- optionally the original query for logging or narrow rewrite behavior

This is a hard rule:

- tools should not re-read raw parser output
- tools should not directly pull session state from Redis
- tools should not rediscover active objects on their own
- tools should not quietly re-run high-level routing logic

If a tool needs context, that context should be injected explicitly.

## Canonical Naming

The tools layer should align to the current architecture vocabulary:

- `IngestionBundle`
- `ResolvedObjectState`
- `DialogueActResult`
- `ModalityDecision`
- `ExecutionIntent`
- `resolved object constraint`
- `ToolRequest`
- `ToolResult`

Interpretation note:

- `DialogueActResult` and `ModalityDecision` may appear nested inside `ExecutionIntent` and `ToolRequest`
- they are not separate top-level layer inputs to tools

Avoid older path-style naming when the design means a tool contract.

## Core Tool Contracts

### `ToolRequest`

Suggested shape:

```python
{
    "tool_name": str,
    "query": str,
    "primary_object": ObjectCandidate | None,
    "secondary_objects": list[ObjectCandidate],
    "dialogue_act": DialogueActResult,
    "modality_decision": ModalityDecision,
    "constraints": {
        "resolved_object_constraint": dict,
        "attribute_constraints": list[dict],
        "attachment_pointers": list[dict],
        "debug_context": dict,
    },
}
```

Recommended interpretation:

- `tool_name`
  - the normalized capability name selected by routing
- `query`
  - the user query or rewritten retrieval query when needed
- `primary_object`
  - the main object this tool should operate on
- `secondary_objects`
  - any supporting objects still relevant to hybrid execution
- `dialogue_act`
  - interaction-level context such as `INQUIRY`, `SELECTION`, or `ELABORATE`
- `modality_decision`
  - the information modality contract already decided upstream
- `constraints`
  - explicitly injected execution constraints

### `ToolResult`

Suggested shape:

```python
{
    "tool_name": str,
    "status": "ok" | "partial" | "empty" | "error",
    "primary_records": list[dict],
    "supporting_records": list[dict],
    "structured_facts": dict,
    "unstructured_snippets": list[dict],
    "artifacts": list[dict],
    "errors": list[str],
    "debug_info": dict,
}
```

Recommended interpretation:

- `primary_records`
  - the most important machine-readable output rows or items
- `supporting_records`
  - additional records that are useful but not dominant
- `structured_facts`
  - normalized facts for grounded rendering
- `unstructured_snippets`
  - text evidence or retrieved chunks
- `artifacts`
  - file pointers, URLs, or report handles
- `debug_info`
  - execution metadata for observability

### `ToolCapability`

Suggested shape:

```python
{
    "tool_name": str,
    "supported_object_types": list[str],
    "supported_dialogue_acts": list[str],
    "supported_modalities": list[str],
    "can_run_in_parallel": bool,
    "returns_structured_facts": bool,
    "returns_unstructured_snippets": bool,
    "requires_external_system": bool,
}
```

This gives execution planning a way to understand what each tool is for without
hard-coding that logic everywhere.

## Ideal Directory Shape

Ignoring the current repo layout, the ideal shape would be:

```text
src/tools/
  __init__.py
  base.py
  contracts.py
  registry.py
  catalog/
    __init__.py
    tool.py
    service.py
  rag/
    __init__.py
    tool.py
    service.py
  documents/
    __init__.py
    tool.py
    service.py
  pricing/
    __init__.py
    tool.py
    service.py
  operations/
    __init__.py
    order_tool.py
    shipping_tool.py
    invoice_tool.py
```

## Module Responsibilities

### `base.py`

Defines the shared tool interface.

Example responsibilities:

- common execute signature
- shared validation helpers
- standard result status handling

### `contracts.py`

Defines:

- `ToolRequest`
- `ToolResult`
- `ToolCapability`

This should be the schema anchor for all tool execution.

### `registry.py`

Registers available tools and their capabilities.

Responsibilities:

- capability discovery
- tool lookup by normalized name
- compatibility checks against object type, dialogue act, and modality

### `catalog/tool.py`

Responsible for product-structured lookup execution.

This tool should answer questions like:

- what is this catalog item?
- what applications are listed?
- what species reactivity is recorded?
- what is the lead time or price if available?

It should not decide whether product ambiguity requires clarification.

### `rag/tool.py`

Responsible for unstructured technical retrieval.

This tool should answer questions like:

- what is the service plan?
- what models are supported?
- what workflow step comes next?
- what validation details are described?
- what technical detail is present in product docs?

It should consume resolved object constraints rather than performing upstream
scope resolution itself.

### `documents/tool.py`

Responsible for document-oriented lookup.

Use cases:

- brochure retrieval
- protocol retrieval
- datasheet retrieval
- file-backed document matching

This tool should prefer deterministic file pointers when attachment signals or
document identifiers are available.

### `pricing/tool.py`

Responsible for price and quote-related lookups or preparation.

Use cases:

- explicit price lookup
- quote preparation
- pricing metadata retrieval

### `operations/order_tool.py`

Responsible for order status and order metadata retrieval.

### `operations/shipping_tool.py`

Responsible for shipment and tracking related retrieval.

### `operations/invoice_tool.py`

Responsible for invoice detail lookup.

## Canonical Tool Set

Recommended first-class tool names:

- `catalog_lookup_tool`
- `technical_rag_tool`
- `document_lookup_tool`
- `pricing_lookup_tool`
- `order_lookup_tool`
- `shipping_lookup_tool`
- `invoice_lookup_tool`

These names should be treated as execution-layer capability names, not route
names.

## Tool Selection Philosophy

The selection rule should be:

- routing decides which tools should run
- tools decide how their internal retrieval executes

This means a turn may produce:

- one tool
- multiple tools
- zero business tools plus a clarification action

### Examples

#### `product + INQUIRY + structured_lookup`

Selected tools:

- `catalog_lookup_tool`

#### `product + INQUIRY + hybrid`

Selected tools:

- `catalog_lookup_tool`
- `technical_rag_tool`

#### `service + INQUIRY + unstructured_retrieval`

Selected tools:

- `technical_rag_tool`

#### `product + SELECTION`

Selected tools:

- no business lookup tool yet
- first update active object state
- then continue normal inquiry execution if the turn continues

#### `order + INQUIRY + external_api`

Selected tools:

- `order_lookup_tool`
- optionally `shipping_lookup_tool`

## Tool Behavior Rules

### Rule 1: Tools Consume Constraints, They Do Not Rediscover Them

If routing or execution already knows:

- the product identifier
- the service name
- the active candidate set
- the document pointer

then the tool should consume those constraints directly.

It should not reopen the whole reasoning problem from scratch.

### Rule 2: Tools May Refine Retrieval, But Not Re-Route

A tool may:

- rank candidates
- rewrite a retrieval query
- expand retrieval terms
- normalize a product identifier for matching

but it should not:

- decide handoff
- decide clarification vs execution
- reinterpret the whole turn as another business path

### Rule 3: Tools Must Be Grounded

Each tool should return:

- machine-readable facts
- grounded snippets
- deterministic artifacts

not free-form final answers.

Grounded rendering belongs downstream in the response layer.

### Rule 4: Tools Must Be Observable

Every tool should expose enough debug information to answer:

- what constraint did it receive?
- what records did it search?
- what records did it return?
- why did it return empty or partial results?

### Rule 5: Tools Should Be Stateless At Runtime

Tools should not own thread-level memory.

They may receive:

- `stateful_anchors`
- `active_object`
- `pending_candidate_options`

but only through injected request contracts.

## Single-Tool vs Multi-Tool Execution

The tools layer itself should not decide orchestration policy, but it should be
designed to support:

- single-tool execution
- sequential multi-tool execution
- parallel independent tool execution

That means tool results must be mergeable.

Examples:

### Product Hybrid Answer

Tools:

- `catalog_lookup_tool`
- `technical_rag_tool`

Expected result pattern:

- catalog tool provides the primary structured fact spine
- technical RAG provides supporting validation or protocol detail

### Service + Documents

Tools:

- `technical_rag_tool`
- `document_lookup_tool`

Expected result pattern:

- technical RAG provides the main answer body
- document lookup provides artifacts or supporting deliverables

## One Tool vs One World

This design rejects the older mental model:

- "go to catalog"
- "go to RAG"
- "go to operations"

Instead, the system should think:

- resolve object
- resolve act
- resolve modality
- select one or more tools

That is what makes:

- hybrid answers natural
- catalog and RAG feel like peers
- operational lookups behave like tools instead of separate worlds

## Current Codebase Mapping

The current codebase already contains tool-like behavior in:

- [catalog_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/catalog_tools.py)
- [rag_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/rag_tools.py)
- [order_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/order_lookup.py)
- [invoice_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/invoice_lookup.py)
- [shipping_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/shipping_lookup.py)

But the architecture still partially treats them as business paths.

The redesign should therefore:

- preserve these implementation assets
- shrink route-level special casing
- standardize tool contracts around one request/result model

## Migration Strategy

### Phase 1: Define Contracts

- define `ToolRequest`
- define `ToolResult`
- define `ToolCapability`
- add a lightweight tool registry

### Phase 2: Wrap Existing Tools Behind Shared Contracts

- adapt catalog tool behavior to `ToolRequest`
- adapt RAG tool behavior to `ToolRequest`
- adapt operational tools to `ToolRequest`

Do not rewrite all tool internals at once.

### Phase 3: Move Selection Logic Upstream

- route and execution planning decide which tools run
- tools stop behaving like route selectors

### Phase 4: Make Tool Results Mergeable

- standardize structured facts
- standardize snippet payloads
- standardize debug metadata

### Phase 5: Connect To Response Synthesis

- response layer consumes one or more `ToolResult`
- final answer remains grounded in returned facts and snippets

## Testing Strategy

The tools layer should be validated at four levels:

### 1. Capability Contract Tests

Test whether each tool declares the correct:

- object support
- act support
- modality support

### 2. Request Validation Tests

Test whether malformed or underspecified tool requests fail safely.

### 3. Result Contract Tests

Test whether each tool returns:

- status
- structured facts
- snippets
- debug metadata

in the agreed format.

### 4. Multi-Tool Composition Tests

Test whether:

- `catalog_lookup_tool + technical_rag_tool`
- `technical_rag_tool + document_lookup_tool`
- `order_lookup_tool + shipping_lookup_tool`

produce mergeable outputs for downstream response synthesis.

## Summary

The tools layer should be the capability layer of the agent.

Its job is simple:

1. receive resolved constraints
2. execute a bounded capability
3. return structured results

It should not:

- perform upstream reasoning
- pretend to be a route
- own final wording

That separation is what will make:

- routing cleaner
- execution planning simpler
- response synthesis more grounded
- catalog, RAG, and API calls feel like one unified tool ecosystem
