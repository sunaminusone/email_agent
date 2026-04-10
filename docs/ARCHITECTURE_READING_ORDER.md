# Architecture Reading Order

This document is the entrypoint for the current design set.

Its purpose is to answer two questions quickly:

1. in what order should these design documents be read?
2. what distinct responsibility does each document own?

## Current Canonical Documents

The current architecture set consists of:

- [INGESTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_LAYER_DESIGN.md)
- [OBJECTS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/OBJECTS_LAYER_DESIGN.md)
- [ROUTING_REDESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_REDESIGN.md)
- [TOOLS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/TOOLS_LAYER_DESIGN.md)
- [EXECUTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EXECUTION_LAYER_DESIGN.md)
- [MEMORY_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/MEMORY_LAYER_DESIGN.md)
- [RESPONSE_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RESPONSE_LAYER_DESIGN.md)
- [RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md)
- [SERVICE_PAGE_RAG_STANDARD.md](/Users/promab/anaconda_projects/email_agent/docs/SERVICE_PAGE_RAG_STANDARD.md)
- [EVAL_OBSERVABILITY_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EVAL_OBSERVABILITY_DESIGN.md)
- [LANGCHAIN_INTEGRATION_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/LANGCHAIN_INTEGRATION_DESIGN.md)
- [IMPLEMENTATION_ROADMAP.md](/Users/promab/anaconda_projects/email_agent/docs/IMPLEMENTATION_ROADMAP.md)

## Recommended Reading Order

Read these documents in the following order:

1. [INGESTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_LAYER_DESIGN.md)
2. [OBJECTS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/OBJECTS_LAYER_DESIGN.md)
3. [ROUTING_REDESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_REDESIGN.md)
4. [TOOLS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/TOOLS_LAYER_DESIGN.md)
5. [EXECUTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EXECUTION_LAYER_DESIGN.md)
6. [MEMORY_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/MEMORY_LAYER_DESIGN.md)
7. [RESPONSE_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RESPONSE_LAYER_DESIGN.md)
8. [RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md)
9. [SERVICE_PAGE_RAG_STANDARD.md](/Users/promab/anaconda_projects/email_agent/docs/SERVICE_PAGE_RAG_STANDARD.md)
10. [EVAL_OBSERVABILITY_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EVAL_OBSERVABILITY_DESIGN.md)
11. [LANGCHAIN_INTEGRATION_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/LANGCHAIN_INTEGRATION_DESIGN.md)
12. [IMPLEMENTATION_ROADMAP.md](/Users/promab/anaconda_projects/email_agent/docs/IMPLEMENTATION_ROADMAP.md)

Reason:

- `ingestion` defines the signal contract
- `objects` defines object resolution on top of that contract
- `routing` defines decision-making after object resolution
- `tools` defines capability contracts
- `execution` defines how selected tools are run
- `memory` defines typed reusable state
- `response` defines grounded expression contracts
- `rag` defines one specific tool family under the new architecture
- `service-page standard` defines the corpus assumptions that make service RAG work well
- `eval / observability` defines how layer behavior is verified and traced
- `LangChain integration` explains how to implement the architecture without collapsing it
- `roadmap` defines migration order

## Responsibility Matrix

| Document | Main Responsibility | Input | Output |
| --- | --- | --- | --- |
| [INGESTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_LAYER_DESIGN.md) | Gather and normalize turn evidence | Raw turn, parser, deterministic extraction, prior state anchors | `IngestionBundle` |
| [OBJECTS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/OBJECTS_LAYER_DESIGN.md) | Resolve products, services, operational objects, ambiguity, and active object state | `IngestionBundle` | `ResolvedObjectState` |
| [ROUTING_REDESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_REDESIGN.md) | Internally resolve dialogue act, modality, and tools, then emit one executable decision | `ResolvedObjectState` | `ExecutionIntent` |
| [TOOLS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/TOOLS_LAYER_DESIGN.md) | Define the capability contracts exposed to orchestration | `ExecutionIntent` and injected constraints | `ToolRequest` and `ToolResult` |
| [EXECUTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EXECUTION_LAYER_DESIGN.md) | Turn one execution intent into planned and executed tool runs | `ExecutionIntent` | `ExecutionPlan` and `ExecutionRun` |
| [MEMORY_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/MEMORY_LAYER_DESIGN.md) | Preserve typed reusable state across turns | prior turn state and turn outcomes | `MemorySnapshot`, `MemoryUpdate`, and `stateful_anchors` |
| [RESPONSE_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RESPONSE_LAYER_DESIGN.md) | Turn grounded execution output into final user-facing replies | `ExecutionRun` and response memory | `ComposedResponse` |
| [RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md) | Define how technical retrieval should behave once object constraints are known | `ExecutionIntent` or resolved object constraints for retrieval | `RetrievalQueryPlan` and grounded retrieval results |
| [SERVICE_PAGE_RAG_STANDARD.md](/Users/promab/anaconda_projects/email_agent/docs/SERVICE_PAGE_RAG_STANDARD.md) | Define the authoring and metadata standard for service-page corpora | Service-page source content | RAG-ready documents and section metadata |
| [EVAL_OBSERVABILITY_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EVAL_OBSERVABILITY_DESIGN.md) | Define how each layer is evaluated and traced | layer contracts and runtime artifacts | eval contracts, trace payloads, and metric families |
| [LANGCHAIN_INTEGRATION_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/LANGCHAIN_INTEGRATION_DESIGN.md) | Explain how LangChain can implement, but not replace, the typed architecture | architecture contracts and layer boundaries | integration guidance |
| [IMPLEMENTATION_ROADMAP.md](/Users/promab/anaconda_projects/email_agent/docs/IMPLEMENTATION_ROADMAP.md) | Define phased migration order for landing the architecture in code | the full design set | staged refactor plan |

## Data Flow

The intended architecture flow is:

1. `ingestion` emits `IngestionBundle`
2. `objects` consumes `IngestionBundle` and emits `ResolvedObjectState`
3. `routing` consumes resolved object state, internally resolves `DialogueActResult` and `ModalityDecision`, and emits `ExecutionIntent`
4. tools such as technical RAG consume the relevant object-scoped constraints from that intent
5. `response` later composes grounded outputs from tool results

Expressed more compactly:

```text
Raw Turn
  -> IngestionBundle
  -> ResolvedObjectState
  -> ExecutionIntent
  -> Tool Results
  -> Response
```

## Layer Order vs Runtime Order

Two different kinds of "order" appear across the design set.

They should not be confused.

### Conceptual Layer Order

This describes the static architecture and dependency boundaries:

```text
ingestion
  -> objects
  -> routing
  -> tools
  -> execution
  -> response
```

In this view:

- `tools` is the capability layer
- `execution` is the orchestration layer that knows how to call tools

### Runtime Invocation Order

This describes what actually happens when one turn is processed:

```text
raw turn
  -> ingestion
  -> objects
  -> routing
  -> execution
  -> tool calls
  -> response
```

In this view:

- `execution` receives `ExecutionIntent`
- `execution` invokes one or more tools
- tools do not run before execution on their own

This distinction matters because the architecture can truthfully say both:

- `tools` is a layer above which execution depends
- `execution` is the runtime layer that actually calls tools

## Canonical Terms

These names should be treated as the preferred vocabulary across all design documents:

- `IngestionBundle`
- `ResolvedObjectState`
- `DialogueActResult`
- `ModalityDecision`
- `ExecutionIntent`
- `resolved object constraint`
- `stateful_anchors`

Interpretation note:

- `DialogueActResult` and `ModalityDecision` are standard routing subcontracts
- they are usually resolved inside `routing`
- `ExecutionIntent` is the canonical external routing output

Prefer these over older mixed terms such as:

- `effective scope`
- `resolved scope`
- `scope-gated rewrite`
- generic `route decision` when the document really means `ExecutionIntent`

## What Each Document Should Not Do

### [INGESTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_LAYER_DESIGN.md)

Should not:

- resolve primary objects
- choose tools
- choose modality

### [OBJECTS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/OBJECTS_LAYER_DESIGN.md)

Should not:

- read raw parser output directly
- read Redis or session state directly
- choose tools
- execute retrieval

### [ROUTING_REDESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_REDESIGN.md)

Should not:

- perform object extraction
- perform object resolution
- perform retrieval directly

### [TOOLS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/TOOLS_LAYER_DESIGN.md)

Should not:

- perform object resolution
- choose tools from scratch
- read session state directly
- generate final user-facing replies

### [EXECUTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EXECUTION_LAYER_DESIGN.md)

Should not:

- re-derive routing decisions
- perform object resolution
- treat tools as self-orchestrating
- generate final user-facing replies

### [MEMORY_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/MEMORY_LAYER_DESIGN.md)

Should not:

- behave like a second routing layer
- perform object resolution
- generate retrieval queries
- generate final responses

### [RESPONSE_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RESPONSE_LAYER_DESIGN.md)

Should not:

- re-run routing
- re-select tools
- retrieve fresh evidence on its own
- invent facts not present in execution results

### [RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md)

Should not:

- own object resolution
- override routing
- become a second orchestration layer

### [SERVICE_PAGE_RAG_STANDARD.md](/Users/promab/anaconda_projects/email_agent/docs/SERVICE_PAGE_RAG_STANDARD.md)

Should not:

- define routing behavior
- define object resolution behavior
- define response policy

### [EVAL_OBSERVABILITY_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EVAL_OBSERVABILITY_DESIGN.md)

Should not:

- redefine runtime business logic
- act as a second routing layer
- bypass typed runtime contracts
- require manual inspection for every routine regression

## Current Gaps

The core architecture stack is now documented.

There are no major missing layer documents at this point.

The remaining work is mainly:

- contract cleanup
- implementation
- migration sequencing
- future refinement of specific subsystems

## Practical Use

If you are implementing:

- new signal extraction logic
  - start with [INGESTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_LAYER_DESIGN.md)
- new object normalization or ambiguity handling
  - start with [OBJECTS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/OBJECTS_LAYER_DESIGN.md)
- new tool routing or hybrid execution logic
  - start with [ROUTING_REDESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_REDESIGN.md)
- service-page technical retrieval behavior
  - read both [RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md) and [SERVICE_PAGE_RAG_STANDARD.md](/Users/promab/anaconda_projects/email_agent/docs/SERVICE_PAGE_RAG_STANDARD.md)
