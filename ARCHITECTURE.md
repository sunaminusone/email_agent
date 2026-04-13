# Architecture

This document summarizes the current target architecture (v3).

The canonical design lives at [docs/AGENT_ARCHITECTURE_V3.md](docs/AGENT_ARCHITECTURE_V3.md). This root document is a compact overview.

## Design Philosophy

This system is an **agent**, not a pipeline.

An agent:
- understands the user's message
- autonomously decides which tools to use
- executes tools and observes results
- iterates if results are insufficient
- synthesizes a coherent response

Each module is independent. Cross-module communication happens through typed Pydantic contracts. LangChain is used as an implementation framework where it adds value, but never replaces the architectural contracts.

## Runtime Flow

```text
user message + memory
  -> ingestion        (understand)
  -> objects           (resolve entities)
  -> routing           (decide: execute / clarify / handoff)
  -> executor          (reason + dispatch tools + observe, may loop)
  -> responser         (synthesize reply)
  -> memory update     (persist state)
```

In concrete terms:

1. `ingestion` emits `IngestionBundle`
2. `objects` emits `ResolvedObjectState`
3. `routing` emits `RouteDecision`
4. `executor` emits `ExecutionResult` (contains plan + tool results)
5. `responser` emits `AgentResponse`
6. `memory` persists `MemoryUpdate`

## Agent Loop

```python
def run_email_agent(request):
    memory = load_memory(request.thread_id)

    # understand
    parsed = ingestion.parse(request.query, memory)
    objects = objects.resolve(parsed)

    # decide
    route = routing.decide(parsed, objects)

    # execute (with reasoning loop)
    results = None
    if route.action == "execute":
        results = executor.run(parsed, objects, memory)

    # respond (all routes)
    response = responser.respond(parsed, route, results)

    # remember
    update_memory(memory, parsed, objects, route, results, response)

    return response
```

## Module Responsibilities

### `src/ingestion/`

Purpose: parse user message, extract signals, resolve references

Input: raw query, conversation history, attachments, prior state

Output: `IngestionBundle`

Should not: resolve entities, select tools, generate replies

### `src/objects/`

Purpose: resolve products, services, orders, invoices, and ambiguity

Input: `IngestionBundle`

Output: `ResolvedObjectState`

Should not: select tools, execute retrieval, read session state directly

### `src/routing/`

Purpose: decide the action route (execute / clarify / handoff)

Input: `IngestionBundle`, `ResolvedObjectState`

Output: `RouteDecision`

Should not: select tools (that is the executor's job), execute retrieval, generate replies

### `src/executor/`

Purpose: autonomously select tools, dispatch calls, observe results, iterate if needed

Input: `IngestionBundle`, `ResolvedObjectState`, `MemorySnapshot`

Output: `ExecutionResult`

Contains an internal reasoning loop:
1. read tool capabilities from registry
2. decide which tools to call and with what parameters
3. dispatch tool calls (parallel when possible)
4. observe results, evaluate completeness
5. if insufficient, plan additional tool calls
6. return aggregated results

Should not: perform ingestion, resolve entities, generate final replies

### `src/tools/`

Purpose: define self-describing tool capabilities, register tools, dispatch requests

Input: `ToolRequest`

Output: `ToolResult`

Each tool declares its own `ToolCapability` (supported object types, intents, parameters). The executor reads these capabilities from the registry to make autonomous tool selection decisions.

Adding a new tool = one file in `tools/` with implementation + capability declaration. No changes to executor, routing, or any other module.

Should not: resolve entities, select other tools, generate final replies

### `src/responser/`

Purpose: synthesize coherent user-facing reply from any route's output

Input: `IngestionBundle`, `RouteDecision`, `ExecutionResult` (if any)

Output: `AgentResponse`

Should not: select tools, execute retrieval, invent facts not grounded in execution results

### `src/memory/`

Purpose: preserve typed state across turns

Primary contracts: `MemorySnapshot`, `MemoryUpdate`, `ThreadMemory`, `ObjectMemory`, `ClarificationMemory`, `ResponseMemory`, `StatefulAnchors`

Should not: act as a routing layer, generate replies

## Capability Layers

These modules answer domain questions. They are called by tools, not by orchestration layers.

### `src/catalog/`
- structured product lookup over PostgreSQL
- candidate retrieval, ranking, and selection

### `src/documents/`
- structured document inventory lookup

### `src/rag/`
- semantic technical retrieval
- service-page vector search and reranking

### `src/integrations/`
- low-level external system connectors (QuickBooks)

## LangChain Integration

LangChain is the implementation framework, not the architecture.

| Module | LangChain Usage |
| --- | --- |
| ingestion | parser chain (structured extraction) |
| objects | mostly deterministic; optional LLM fallback for rare ambiguity |
| routing | mostly deterministic; optional LLM classifier fallback |
| executor | LangGraph for reasoning loop; LCEL for tool composition |
| tools | wrap as LangChain Tools for standardized invocation |
| responser | LLM-based response synthesis and rewrite |
| memory | own typed contracts; LangChain memory not used |

Core rule: all cross-module communication uses our own Pydantic contracts, never raw LangChain objects.

## Key Differences From v2

| Aspect | v2 (previous) | v3 (current) |
| --- | --- | --- |
| Tool selection | routing rules + planner rules (two places) | executor reads tool capabilities from registry |
| Execution | single pass, no iteration | reasoning loop with observation |
| Adding a new tool | change routing + planner + requests + tool | add one file in tools/ |
| Planner | separate module between routing and executor | absorbed into executor's reasoning step |
| Response | `response/` | `responser/` |
| Routing scope | decides route + selects tools | decides route only |

## Canonical Vocabulary

Preferred terms across docs and code:

- `IngestionBundle`
- `ResolvedObjectState`
- `RouteDecision`
- `ToolCapability`
- `ToolRequest` / `ToolResult`
- `ExecutionResult`
- `AgentResponse`
- `MemorySnapshot` / `MemoryUpdate`

## Reading Order

1. [docs/AGENT_ARCHITECTURE_V3.md](docs/AGENT_ARCHITECTURE_V3.md) — this design
2. [docs/INGESTION_LAYER_DESIGN.md](docs/INGESTION_LAYER_DESIGN.md) — signal contracts
3. [docs/OBJECTS_LAYER_DESIGN.md](docs/OBJECTS_LAYER_DESIGN.md) — entity resolution
4. [docs/TOOLS_LAYER_DESIGN.md](docs/TOOLS_LAYER_DESIGN.md) — capability contracts
5. [docs/MEMORY_LAYER_DESIGN.md](docs/MEMORY_LAYER_DESIGN.md) — typed state
6. [docs/RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md](docs/RAG_RETRIEVAL_ENHANCEMENT_DESIGN.md) — technical retrieval
7. [docs/SERVICE_PAGE_RAG_STANDARD.md](docs/SERVICE_PAGE_RAG_STANDARD.md) — corpus standard
