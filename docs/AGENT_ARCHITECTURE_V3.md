# Agent Architecture v3

## Overview

This document defines the target architecture for the biotech customer support agent. It supersedes the v2 pipeline design.

The system serves two primary use cases:
1. **Technical consultation** (~60%): domain-specific knowledge retrieval via RAG
2. **Business queries** (~40%): product, order, invoice, and shipping lookups via PostgreSQL and QuickBooks API

Mixed queries (technical + business in one message) must be handled naturally.

## Design Principles

1. **Agent, not pipeline** — the system reasons about what to do, acts, observes, and iterates
2. **Module independence** — each module has a typed contract; changing one module does not require changing others
3. **Tool self-description** — tools declare their own capabilities; the executor discovers and selects tools at runtime
4. **LangChain as framework, not architecture** — LangChain/LangGraph helps implement modules; Pydantic contracts define the boundaries
5. **Incremental upgrade** — the new design reuses existing code wherever possible

## Architecture Diagram

```
                         ┌─────────────────────────────────────┐
                         │            Memory                    │
                         │   MemorySnapshot / MemoryUpdate      │
                         └──────┬──────────────────┬───────────┘
                                │ read             │ write
                                ▼                  │
User Message ──▶ ┌──────────────────┐              │
                 │    Ingestion      │              │
                 │                   │              │
                 │  parse + extract  │              │
                 │  signals          │              │
                 └────────┬─────────┘              │
                          │ IngestionBundle         │
                          ▼                         │
                 ┌──────────────────┐              │
                 │    Objects        │              │
                 │                   │              │
                 │  resolve entities │              │
                 │  detect ambiguity │              │
                 └────────┬─────────┘              │
                          │ ResolvedObjectState     │
                          ▼                         │
                 ┌──────────────────┐              │
                 │    Routing        │              │
                 │                   │              │
                 │  execute?         │              │
                 │  clarify?         │              │
                 │  handoff?         │              │
                 └────────┬─────────┘              │
                          │ RouteDecision           │
                          ▼                         │
                 ┌──────────────────┐              │
                 │    Executor       │              │
                 │                   │              │
                 │  ┌─── loop ────┐ │    ┌────────────────┐
                 │  │ reason      │ │    │    Tools        │
                 │  │ dispatch  ──│─│───▶│ (self-describing│
                 │  │ observe     │ │◀───│  capabilities)  │
                 │  │ enough?     │ │    └────────────────┘
                 │  └─────────────┘ │
                 └────────┬─────────┘
                          │ ExecutionResult
                          ▼
                 ┌──────────────────┐              │
                 │    Responser      │              │
                 │                   │              │
                 │  synthesize reply │──────────────┘
                 └────────┬─────────┘
                          │ AgentResponse
                          ▼
                    Final Reply
```

## Module Directory Structure

```
src/
├── app/
│   └── service.py              # Agent loop orchestration
│
├── ingestion/                   # Understanding layer
│   ├── pipeline.py              #   main orchestrator
│   ├── parser_adapter.py        #   LLM parser chain (LangChain)
│   ├── normalizers.py           #   text normalization
│   ├── deterministic_signals.py #   rule-based signal extraction
│   ├── reference_signals.py     #   pronoun / reference resolution
│   ├── signal_refinement.py     #   post-processing refinement
│   ├── stateful_anchors.py      #   session state extraction
│   ├── parser_prompt.py         #   parser prompt template
│   └── models.py                #   IngestionBundle, TurnCore, signals
│
├── objects/                     # Entity resolution layer
│   ├── resolution.py            #   main orchestrator
│   ├── extraction.py            #   candidate generation
│   ├── constraint_matching.py   #   attribute filtering
│   ├── extractors/              #   type-specific extractors
│   │   ├── product_extractor.py
│   │   ├── service_extractor.py
│   │   └── operational_extractor.py
│   └── models.py                #   ObjectCandidate, ResolvedObjectState
│
├── routing/                     # Decision layer (route only, no tool selection)
│   ├── runtime.py               #   main entry
│   ├── orchestrator.py          #   stage pipeline
│   ├── stages/
│   │   ├── dialogue_act.py      #   classify intent type
│   │   ├── modality.py          #   text / structured / hybrid
│   │   └── object_routing.py    #   validate object state
│   ├── policies/
│   │   ├── clarification.py     #   should we ask for more info?
│   │   └── handoff.py           #   should we escalate to human?
│   └── models.py                #   RouteDecision
│
├── executor/                    # Reasoning + execution layer
│   ├── engine.py                #   reasoning loop (LangGraph)
│   ├── tool_selector.py         #   reads registry, selects tools
│   ├── request_builder.py       #   builds ToolRequest from context
│   ├── dispatcher.py            #   dispatches tool calls
│   ├── completeness.py          #   evaluates if results are sufficient
│   ├── merger.py                #   merges multi-tool results
│   └── models.py                #   ExecutionResult, ExecutionContext
│
├── tools/                       # Self-describing tool set
│   ├── registry.py              #   tool registration and discovery
│   ├── base.py                  #   base tool interface
│   ├── models.py                #   ToolCapability, ToolRequest, ToolResult
│   ├── catalog/                 #   product catalog (PostgreSQL)
│   ├── rag/                     #   technical knowledge (Chroma)
│   ├── documents/               #   document lookup
│   └── quickbooks/              #   order, invoice, shipping (QuickBooks API)
│
├── responser/                   # Response synthesis layer
│   ├── service.py               #   main orchestrator
│   ├── blocks.py                #   content block extraction
│   ├── composer.py              #   LLM rewrite (LangChain)
│   ├── renderers/               #   route-specific renderers
│   │   ├── answer.py
│   │   ├── clarification.py
│   │   ├── handoff.py
│   │   ├── acknowledgement.py
│   │   └── termination.py
│   ├── resolution.py            #   topic / style derivation
│   └── models.py                #   AgentResponse, ContentBlock
│
├── memory/                      # Session state persistence
│   ├── session_store.py         #   Redis-backed session management
│   ├── store.py                 #   snapshot load / apply / serialize
│   ├── adapters/
│   │   └── redis_store.py       #   Redis adapter
│   ├── thread_memory.py         #   thread-level state updates
│   ├── object_memory.py         #   object-level state updates
│   ├── clarification_memory.py  #   pending clarification state
│   ├── response_memory.py       #   response history state
│   └── models.py                #   MemorySnapshot, MemoryUpdate, etc.
│
├── common/
│   └── models.py                #   ObjectRef, SourceAttribution, shared types
│
├── catalog/                     #   product search pipeline (PostgreSQL)
├── documents/                   #   document search pipeline
├── rag/                         #   RAG pipeline (Chroma + reranker)
├── integrations/
│   └── quickbooks/              #   QuickBooks OAuth + API
│
└── config/
    └── settings.py              #   environment config
```

## Data Contracts

### Cross-Module Contracts

```
Module          Input                              Output
─────────────── ────────────────────────────────── ──────────────────────
Ingestion       raw query, history, memory         IngestionBundle
Objects         IngestionBundle                    ResolvedObjectState
Routing         IngestionBundle, ResolvedObjState  RouteDecision
Executor        IngestionBundle, ResolvedObjState  ExecutionResult
Responser       RouteDecision, ExecutionResult     AgentResponse
Memory          all of the above                   MemoryUpdate
```

### Key Models

```python
# ingestion
class IngestionBundle:
    turn_core: TurnCore               # thread_id, raw/normalized query, language
    turn_signals: TurnSignals         # parser + deterministic + reference signals

# objects
class ResolvedObjectState:
    primary_object: ObjectCandidate | None
    secondary_objects: list[ObjectCandidate]
    ambiguous_sets: list[AmbiguousObjectSet]
    active_object: ObjectCandidate | None
    resolution_confidence: float

# routing
class RouteDecision:
    action: Literal["execute", "clarify", "handoff"]
    dialogue_act: DialogueActResult   # INQUIRY, REQUEST, INFORM, etc.
    modality: ModalityDecision        # text, structured, hybrid
    clarification: ClarificationPayload | None

# executor
class ExecutionResult:
    tool_calls: list[ExecutedToolCall]
    merged_results: MergedResults
    iterations: int                   # how many reasoning loops
    final_status: str

# tools
class ToolCapability:
    tool_name: str
    description: str                  # human-readable, for LLM reasoning
    supported_object_types: list[str]
    supported_intents: list[str]
    required_params: list[str]
    optional_params: list[str]
    returns_structured: bool
    returns_unstructured: bool
    can_run_in_parallel: bool

class ToolRequest:
    tool_name: str
    query: str
    constraints: dict

class ToolResult:
    tool_name: str
    status: str
    primary_records: list
    structured_facts: dict
    unstructured_snippets: list
    artifacts: list

# responser
class AgentResponse:
    message: str
    response_type: str
    content_blocks: list[ContentBlock]
    citations: list

# memory
class MemorySnapshot:
    thread_memory: ThreadMemory
    object_memory: ObjectMemory
    clarification_memory: ClarificationMemory
    response_memory: ResponseMemory
```

## Module Details

### 1. Ingestion

**Purpose**: understand what the user said.

**What it does**:
- normalize raw text
- invoke LLM parser chain for intent, entities, confidence (via LangChain)
- extract deterministic signals via regex patterns (catalog numbers, order numbers)
- resolve pronouns and references from conversation history
- extract stateful anchors from prior memory

**LangChain usage**: parser chain (`ChatOpenAI` + structured output parsing)

**Does not**: resolve entities to business objects, select tools, generate replies.

### 2. Objects

**Purpose**: resolve which business entities the user is talking about.

**What it does**:
- extract candidates from ingestion signals (products, services, orders, invoices)
- apply attribute constraints to filter candidates
- score and rank candidates
- detect ambiguity (multiple candidates for the same reference)
- resolve from session context when user says "this product" etc.

**LangChain usage**: minimal. Mostly deterministic logic with optional LLM fallback for rare ambiguity.

**Does not**: select tools, execute retrieval, read session state directly.

### 3. Routing

**Purpose**: decide the overall action route.

Three possible decisions:
- `execute` — the query needs tool execution
- `clarify` — information is missing, ask the user
- `handoff` — escalate to a human agent

Also resolves:
- `DialogueActResult` (INQUIRY, REQUEST, INFORM, ELABORATE, etc.)
- `ModalityDecision` (text, structured, hybrid)

**Key change from v2**: routing no longer selects tools. That responsibility moves to the executor.

**LangChain usage**: optional LLM classifier for dialogue act in ambiguous cases.

**Does not**: select tools, dispatch tool calls, generate replies.

### 4. Executor

**Purpose**: autonomously select and run tools, iterate if needed.

This is the core "agent" behavior module.

**Internal loop**:
```
1. Read all tool capabilities from registry
2. Given parsed input + objects + memory, reason about which tools to call
3. Build ToolRequest for each selected tool
4. Dispatch tool calls (parallel when safe)
5. Observe results
6. Evaluate completeness:
   - all sub-intents answered? → done
   - missing information? → plan additional tool calls → go to step 2
   - max iterations reached? → done with partial results
7. Merge all results into ExecutionResult
```

**LangChain / LangGraph usage**: this is the best fit for LangGraph.
- The reasoning loop maps naturally to a LangGraph state graph
- Tool dispatch can use LangChain tool wrappers
- State transitions are explicit and traceable

**Configuration**:
- `max_iterations`: maximum reasoning loops (default: 3)
- `parallel_dispatch`: whether to run independent tools concurrently

**Does not**: perform ingestion, resolve entities, generate final replies.

### 5. Tools

**Purpose**: provide self-describing, independently deployable capabilities.

Each tool:
1. Declares a `ToolCapability` describing what it can do
2. Registers itself in the tool registry
3. Accepts a `ToolRequest`, returns a `ToolResult`

**Current tools**:

| Tool | Data Source | Object Types | Description |
| --- | --- | --- | --- |
| `catalog_lookup_tool` | PostgreSQL | product | Product catalog search |
| `pricing_lookup_tool` | PostgreSQL | product | Price lookup |
| `technical_rag_tool` | Chroma vectorstore | product, service | Technical knowledge retrieval |
| `document_lookup_tool` | local CSV + PDFs | document | Document metadata search |
| `customer_lookup_tool` | QuickBooks API | customer | Customer record lookup |
| `order_lookup_tool` | QuickBooks API | order | Order status lookup |
| `invoice_lookup_tool` | QuickBooks API | invoice | Invoice lookup |
| `shipping_lookup_tool` | QuickBooks API | order | Shipping / delivery status |

**Adding a new tool** (e.g., `inventory_tool`):
1. Create `src/tools/inventory_tool.py`
2. Define `ToolCapability` with supported object types and intents
3. Implement the executor function
4. Register in the tool registry
5. No changes to routing, executor, or any other module

**LangChain usage**: wrap each tool as a LangChain `Tool` or `StructuredTool` for standardized invocation and tracing.

### 6. Responser

**Purpose**: synthesize a coherent user-facing reply.

**What it does**:
- build content blocks from tool results (structured facts, snippets, artifacts)
- select response mode based on route (answer, clarification, handoff, acknowledgement, termination)
- render a deterministic draft using the appropriate renderer
- optionally pass through LLM rewrite for natural language quality
- emit final `AgentResponse`

**LangChain usage**: LLM-based response composition and rewrite.

**Does not**: select tools, execute retrieval, invent facts.

### 7. Memory

**Purpose**: preserve typed state across conversation turns.

**Memory types**:
- `ThreadMemory`: active route, last goal, business line, phase
- `ObjectMemory`: active/recent objects, candidate sets
- `ClarificationMemory`: pending questions, options, resume route
- `ResponseMemory`: revealed attributes, tool results, topics

**Operations**:
- `load_memory_snapshot(thread_id)` → `MemorySnapshot`
- `apply_memory_update(snapshot, update)` → `MemorySnapshot`
- `persist_memory_snapshot(thread_id, snapshot)` → Redis

**LangChain usage**: none. Memory contracts are richer than LangChain's chat buffer and must remain typed.

## LangChain / LangGraph Integration Summary

```
Module        Framework         Usage
───────────── ───────────────── ─────────────────────────────────────
Ingestion     LangChain         Parser chain (structured extraction)
Objects       (none)            Deterministic logic
Routing       LangChain (opt)   Classifier fallback for edge cases
Executor      LangGraph         Reasoning loop, state graph
Tools         LangChain         Tool wrappers for invocation + tracing
Responser     LangChain         LLM response synthesis and rewrite
Memory        (none)            Own typed contracts via Redis
```

**Rules**:
1. All cross-module data uses Pydantic contracts, never raw LangChain objects
2. LangChain is used inside modules as an implementation detail
3. Do not collapse multiple modules into one LangChain agent prompt
4. Do not replace typed memory with a plain chat buffer

## Migration Path From v2

### Phase 1: Restructure (low risk)

- [x] Split `src/execution/` into `src/executor/` (engine + dispatcher) — move files, update imports
- [ ] Rename `src/response/` to `src/responser/` — move files, update imports
- [ ] Remove tool selection from `routing/stages/tool_routing.py` — routing emits `RouteDecision` without selected tools
- [ ] Update `src/app/service.py` to use new module paths

Existing code reuse:
- `execution/executor.py` → `executor/dispatcher.py`
- `execution/merger.py` → `executor/merger.py`
- `execution/planner.py` + `planner_rules.py` → `executor/tool_selector.py`
- `execution/requests.py` → `executor/request_builder.py`
- `response/*` → `responser/*` (rename only)

### Phase 2: Enhance executor (medium risk)

- [ ] Implement `executor/tool_selector.py` that reads `ToolCapability` from registry instead of hardcoded rules
- [ ] Implement `executor/completeness.py` to evaluate result sufficiency
- [ ] Add reasoning loop in `executor/engine.py` (LangGraph state graph)
- [ ] Implement parallel dispatch via `asyncio.gather`

### Phase 3: Enhance tools (low risk)

- [ ] Enrich `ToolCapability` with `description`, `supported_intents`, `required_params`
- [ ] Wrap tools as LangChain `StructuredTool` for tracing
- [ ] Ensure each tool file declares its own capability (no central mapping tables)

### Phase 4: Clean up (low risk)

- [ ] Remove `routing/stages/tool_routing.py` (tool selection now in executor)
- [ ] Remove `execution/planner_rules.py` hardcoded mapping tables
- [ ] Update design documents to reflect v3
- [ ] Add tests for executor reasoning loop

## Extensibility Examples

### Adding a new tool

Create one file:

```python
# src/tools/inventory_tool.py

CAPABILITY = ToolCapability(
    tool_name="inventory_tool",
    description="Query real-time product inventory and stock levels",
    supported_object_types=["product"],
    supported_intents=["inventory_check", "availability", "stock_level"],
    required_params=["product_identifier"],
    optional_params=["warehouse_location"],
    returns_structured=True,
    returns_unstructured=False,
    can_run_in_parallel=True,
)

def execute(request: ToolRequest) -> ToolResult:
    # implementation
    ...

register_tool("inventory_tool", execute, CAPABILITY)
```

No changes to any other module. The executor discovers and uses it automatically.

### Adding a new route type

Add a new case in `routing/policies/` and a new renderer in `responser/renderers/`.

### Supporting a new object type

Add an extractor in `objects/extractors/` and declare the object type in `common/models.py`.

## Anti-Patterns To Avoid

1. **One giant prompt** — do not collapse ingestion + routing + tool selection + response into a single LLM call
2. **Hardcoded tool mapping tables** — do not maintain `TOOL_BY_OBJECT_TYPE` dicts; let tools self-describe
3. **Raw LangChain objects across modules** — always use Pydantic contracts at module boundaries
4. **Opaque memory** — do not replace typed memory with a plain chat buffer
5. **Tools that re-resolve context** — tools receive explicit parameters via `ToolRequest`, they should not rediscover the active object or pending clarification on their own
