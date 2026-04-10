# LangChain Integration Design

## Goal

This document explains how LangChain should be integrated into the current
object-centric architecture without collapsing the architecture into one prompt
or one monolithic agent loop.

Its purpose is to answer one question:

> How can LangChain be used as an implementation framework while preserving the architectural contracts defined in ingestion, objects, routing, tools, execution, memory, and response?

## Core Principle

Use LangChain as:

- an implementation layer
- an orchestration helper
- a model and tool wrapper layer

Do not use LangChain as:

- the architecture itself
- a replacement for core contracts
- a reason to collapse deterministic layers into one prompt

In short:

- architecture stays ours
- LangChain helps implement it

## What Should Remain Framework-Agnostic

The following architectural contracts should remain independent of LangChain:

- `IngestionBundle`
- `ResolvedObjectState`
- `DialogueActResult`
- `ModalityDecision`
- `ExecutionIntent`
- `ToolRequest`
- `ToolResult`
- `ExecutionPlan`
- `ExecutionRun`
- `ResponsePlan`
- `ComposedResponse`

These contracts define the system's meaning.

LangChain may help produce or consume them, but should not replace them.

## Layer-by-Layer Guidance

## 1. Ingestion

### Good Fit For LangChain

LangChain is a good fit for:

- parser prompts
- structured extraction
- message formatting
- prompt pipelines

Recommended use:

- wrap the parser prompt and model call behind a LangChain adapter
- parse into your own parser-facing schema
- convert that into `IngestionBundle`

### What Not To Do

Do not let LangChain objects become the ingestion contract.

The output of ingestion should still be:

- `IngestionBundle`

not:

- raw LangChain message objects
- ad hoc model JSON
- tool-call traces as implicit state

## 2. Objects

### Use LangChain Sparingly

The objects layer should remain mostly deterministic.

This layer contains:

- canonicalization
- alias matching
- ambiguity grouping
- active-context reuse
- primary object resolution

These are better handled through:

- registries
- deterministic normalization
- explicit scoring and rules

### Allowed Use

LangChain may be used here only as a narrow fallback:

- if a rare ambiguity requires LLM assistance
- if a very weak turn needs optional semantic help

But that should never replace the core object model.

## 3. Routing

### Do Not Turn Routing Into A Prompt Router

Routing should not become:

- one giant prompt that decides everything

That would erase the value of:

- `ResolvedObjectState`
- `DialogueActResult`
- `ModalityDecision`

### Recommended Use

LangChain may help with:

- a bounded dialogue-act classifier
- a bounded modality classifier
- optional model-backed fallback for unclear turns

But routing should still emit:

- `ExecutionIntent`

using your own contracts.

## 4. Tools

### This Is A Strong Fit For LangChain

The tools layer is one of the best places to use LangChain.

Recommended uses:

- wrap each capability as a LangChain Tool or Runnable
- standardize invocation
- reuse tracing and callback hooks

Examples:

- `catalog_lookup_tool`
- `technical_rag_tool`
- `document_lookup_tool`
- `order_lookup_tool`
- `invoice_lookup_tool`
- `shipping_lookup_tool`

### Important Rule

Each tool should still consume:

- `ToolRequest`

and return:

- `ToolResult`

LangChain helps run the tool.

It should not redefine the contract.

## 5. Execution

### This Is The Best Place For LangChain Or LangGraph

Execution is where LangChain becomes especially useful.

Recommended uses:

- Runnable composition
- LCEL graph-style sequencing
- optional parallel execution helpers
- callback tracing

Possible mapping:

- `ExecutionIntent` -> build `ExecutionPlan`
- `ExecutionPlan` -> LangChain Runnable sequence
- tool results -> `ExecutionRun`

### If Using LangGraph

LangGraph becomes useful if execution evolves into:

- clarification loops
- multi-step retries
- branch-aware fallback
- iterative multi-tool plans

But the state passed through the graph should still be your own typed state,
not opaque graph-local state only.

## 6. Memory

### Use LangChain Memory Carefully

LangChain memory abstractions should not replace your typed memory design.

Why:

- your memory needs typed clarification state
- your memory needs active object state
- your memory needs `revealed_attributes`
- your memory needs soft reset semantics

These are richer than a generic chat buffer.

### Recommended Use

Use your own memory contracts:

- `MemorySnapshot`
- `MemoryUpdate`
- `StatefulAnchors`

LangChain memory can be used internally only as an implementation detail if
needed, but it should not become the system's source of truth.

## 7. Response

### Strong Fit For LangChain

The response layer is a very good place to use LangChain.

Recommended uses:

- constrained grounded rewrite
- prompt templating
- model invocation
- output parsing

Suggested pattern:

1. build grounded content blocks deterministically
2. render a deterministic draft
3. optionally pass that draft and the grounded blocks into a constrained
   LangChain composer
4. emit `ComposedResponse`

This preserves:

- determinism
- groundedness
- natural language quality

## Recommended Integration Pattern

The best integration pattern is:

- architecture contracts first
- LangChain adapters second

That means:

- each layer owns a typed contract
- LangChain is used inside adapters and execution flows
- all cross-layer communication stays framework-independent

## Example Mapping

### Ingestion

- LangChain parser chain
  -> `ParsedResult`
  -> `IngestionBundle`

### Objects

- deterministic resolution
  -> `ResolvedObjectState`

### Routing

- deterministic routing plus optional narrow classifiers
  -> internally resolve `DialogueActResult`
  -> internally resolve `ModalityDecision`
  -> `ExecutionIntent`

### Execution

- LangChain Runnable graph or sequence
  -> tool calls
  -> `ExecutionRun`

### Response

- deterministic content assembly
  -> constrained LangChain rewrite
  -> `ComposedResponse`

## Anti-Patterns To Avoid

### 1. One Giant Agent Prompt

Do not collapse:

- ingestion
- objects
- routing
- tool selection
- response synthesis

into one free-form LangChain agent prompt.

This would destroy:

- observability
- testability
- deterministic clarification behavior
- object continuity quality

### 2. Letting Tools Re-Resolve Context

Do not let individual tools use LangChain memory or prompts to rediscover:

- the active object
- the pending clarification
- the intended modality

These should be injected explicitly.

### 3. Skipping Your Typed Contracts

Do not pass:

- raw LangChain messages
- raw tool traces
- prompt JSON blobs

between major layers instead of your own structured contracts.

### 4. Making Memory Opaque

Do not replace typed memory with:

- a plain chat transcript buffer

Your system needs typed memory, not just recalled text.

## Practical Adoption Order

If you want to adopt LangChain gradually, the safest order is:

### Phase 1

Use LangChain in:

- parser adapter
- grounded response rewrite

These are already close fits.

### Phase 2

Wrap existing capability modules as LangChain tools.

Examples:

- catalog lookup
- RAG lookup
- document lookup
- order lookup

### Phase 3

Move execution planning onto Runnable composition or LangGraph while preserving:

- `ExecutionIntent`
- `ExecutionPlan`
- `ExecutionRun`

### Phase 4

Add optional bounded model-backed fallback in:

- dialogue-act classification
- modality selection
- difficult retrieval contextualization

only after the deterministic core is stable.

## Summary

LangChain should help implement the architecture, not replace it.

The clean rule is:

1. keep architectural contracts typed and framework-independent
2. use LangChain inside adapters, tool wrappers, execution graphs, and response composition
3. avoid collapsing deterministic layers into one prompt-driven loop

That gives you:

- better composability
- easier tracing
- stronger reuse of models and tools
- without losing the clarity of the object-centric architecture
