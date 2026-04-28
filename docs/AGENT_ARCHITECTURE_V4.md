# Agent Architecture v4

## Identity

> **This is an internal email co-pilot for ProMab's customer-service reps
> and sales reps. It generates reviewable, high-quality email drafts based
> on similar past replies, relevant documents, and customer context. It
> is not an autonomous customer-facing reply bot.**

This document defines the v4 architecture, which supersedes v3 with the
2026-04-27 product redefinition. The v3 mechanical pieces (typed contracts,
agent loop, two-phase memory, tool framework) are largely unchanged — what
changed is who consumes the output (the rep, not the customer), what the
output is (a draft + reference bundle, not a polished reply), and how
routing's clarify / handoff judgments are interpreted (advisory metadata,
not gates).

## System Use

The agent serves CSRs and sales reps in two directions:

1. **Inbound** — A customer email or HubSpot form inquiry comes in. The
   rep pastes (or the system ingests) the customer message; the agent
   returns a drafted reply alongside the most similar past customer/sales
   conversations and any relevant KB documents.
2. **Outbound** *(planned, P2 of roadmap)* — A sales rep gives a scenario;
   the agent drafts an outreach message in the sales voice.

In both directions, the rep stays in the loop — they review, edit, and
decide whether to send. The agent never speaks directly to a customer.

The original two use-case categories (technical consultation ~60%,
business queries ~40%) still describe the **content distribution** of
incoming inquiries. What changed is that both categories now produce a
draft + reference bundle for the rep, never a customer-facing reply.

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
Inbound inquiry  ┌──────────────────┐              │
(or outbound  ──▶│    Ingestion      │              │
 scenario)       │                   │              │
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
                 │  classify         │              │
                 │  (clarify /       │              │
                 │   handoff are     │              │
                 │   advisory only)  │              │
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
                 │  (csr_draft       │              │
                 │   renderer:       │              │
                 │   draft +         │──────────────┘
                 │   references +    │
                 │   routing notes)  │
                 └────────┬─────────┘
                          │ AgentResponse
                          ▼
              CSR-facing draft bundle
              (the rep reviews, edits, sends)
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
│   ├── rag/                     #   technical knowledge + ★historical threads
│   │   ├── technical_tool.py        # KB chunks (service flyers, workflows)
│   │   ├── historical_thread_tool.py # ★ past HubSpot sales replies (8.8k threads)
│   │   ├── capability.py            # technical_rag_tool capability
│   │   └── historical_capability.py # historical_thread_tool capability
│   ├── documents/               #   document lookup
│   └── quickbooks/              #   order, invoice, shipping (QuickBooks API)
│
├── responser/                   # Response synthesis layer
│   ├── service.py               #   main orchestrator (always dispatches csr_draft)
│   ├── blocks.py                #   content block extraction
│   ├── composer.py              #   LLM rewrite (skipped for csr_draft type)
│   ├── renderers/               #   v4: only csr_draft is dispatched
│   │   ├── csr_draft.py         #   ★ the only renderer used in v4
│   │   ├── answer.py            #   dormant (kept for import safety)
│   │   ├── clarification.py     #   dormant
│   │   ├── handoff.py           #   dormant
│   │   ├── knowledge.py         #   dormant
│   │   ├── partial_answer.py    #   dormant
│   │   ├── acknowledgement.py   #   dormant
│   │   └── termination.py       #   dormant
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

**Purpose**: classify the inquiry's posture and emit a `RouteDecision`. In
v4 the **classification still runs as designed**, but its `clarify` /
`handoff` decisions no longer **gate** retrieval — they become advisory
metadata for the rep.

Three classifications still emitted (for visibility / future use):
- `execute` — straightforward inquiry, no warning
- `clarify` — agent thinks the inquiry is ambiguous (would-have-asked-customer)
- `handoff` — agent thinks this needs expert / AE input

In v4, `_run_agent_loop` (`src/app/service.py`) coerces every group to
`execute` regardless of original classification. The original judgment is
preserved on `route_decision.reason` as an `AI_ROUTING_NOTE` string that
the renderer surfaces in a ⚠️ section of the draft. Rationale: an
ambiguity / handoff judgment is **valuable signal for the rep**; throwing
it away or hiding it serves no one. Blocking retrieval based on it would
mean the rep gets nothing useful exactly when the agent is uncertain.

Also resolves:
- `DialogueActResult` (INQUIRY, REQUEST, INFORM, ELABORATE, etc.)
- `ModalityDecision` (text, structured, hybrid)

**Key change from v2**: routing no longer selects tools. That responsibility moved to the executor in v3.

**Key change from v3**: `clarify` / `handoff` are advisory, not gating.

**LangChain usage**: optional LLM classifier for dialogue act in ambiguous cases.

**Does not**: select tools, dispatch tool calls, generate replies.

### 4. Executor

**Purpose**: autonomously select and run tools, iterate if needed.

This is the core "agent" behavior module.

**v4 invariant — both retrieval tools always run**: regardless of which
tool the demand classifier picks as primary, `select_tools`
(`src/executor/tool_selector.py`) always adds `historical_thread_tool` and
`technical_rag_tool` as supporting selections. Their values are
**complementary**, not substitutional — past sales replies tell the rep
how we historically responded; KB chunks tell the rep what authoritative
documentation says. The CSR sees both and decides.

**Internal loop**:
```
1. Read all tool capabilities from registry
2. Given parsed input + objects + memory, reason about which tools to call
   (CSR mode: historical_thread_tool + technical_rag_tool always included)
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
| `historical_thread_tool` ★v4 | Chroma `historical_threads_v1` | product, service, scientific_target | Past HubSpot sales replies (8.8k threads); always-included in CSR mode |
| `technical_rag_tool` | Chroma `email_agent_rag_v7_service_pages_only` | product, service | Service flyers, workflow docs; always-included in CSR mode |
| `catalog_lookup_tool` | PostgreSQL | product | Product catalog search |
| `pricing_lookup_tool` | PostgreSQL | product | Price lookup |
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

**Purpose**: synthesize the CSR-facing draft bundle.

**v4 invariant — always csr_draft**: `_render_response`
(`src/responser/service.py`) no longer dispatches by `response_mode`. It
always calls `render_csr_draft_response` (`src/responser/renderers/csr_draft.py`),
which produces the Slack-style structured output:

```
📝 Draft reply              — LLM-synthesized, marked clearly as draft
📚 Similar past inquiries   — Top historical threads (full conversation)
📄 Relevant documents       — Top KB chunks
⚠️ AI routing notes         — Only when routing flagged ambiguity / handoff
```

`compose_final_response` (`src/responser/composer.py`) skips its legacy
LLM rewrite when `response_type == "csr_draft"` — the structured sections
must not be collapsed back into a flowing reply.

The seven legacy renderers (`acknowledgement`, `answer`, `clarification`,
`handoff`, `knowledge`, `partial_answer`, `termination`) **are kept** but
never dispatched. They assume customer-facing output, which v4 invalidates.
Cleanup is deferred until we are confident nothing imports them.

**LangChain usage**: LLM call inside `csr_draft.py` to produce the actual
draft from retrieved context.

**Does not**: select tools, execute retrieval, invent facts beyond what
the retrieved threads / docs say.

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

## Quality bar (the 90% commitment)

Drafts target **90% ship-readiness** — the rep should only need small
edits before sending. This is a deliberate stretch from "70% useful
starting point". It pushes design decisions in three directions:

- **Lean heavily on past sales replies as language source** rather than
  generating from generic LLM voice. The historical corpus is what
  ProMab actually sounds like.
- **Cite specific facts (timelines, prices, technical specs) only when
  present in the inputs.** Never invent.
- **When a question is genuinely ambiguous**, draft a brief clarifying
  question to the customer rather than guessing. The CSR can still send
  this draft; it's a useful response by itself.

## Trust calibration (mandatory)

90% is a target, not a guarantee. The rep needs to know when to trust the
draft and when to lean harder on the references / write from scratch. The
renderer must show:

- **"Based on N highly similar past replies"** when top historical hits
  have strong similarity scores
- **"⚠️ No highly similar past inquiries — use caution"** when scores are weak
- **Per-reference scores** in human-friendly framing (very similar /
  somewhat similar / loosely related)
- **Routing notes** (already implemented via AI_ROUTING_NOTE) when the
  agent flagged ambiguity

The retrieval quality tier from `_compute_retrieval_confidence`
(`src/rag/retriever.py`) — originally framed as a confidence "gate" — is
repurposed in v4 as a **search result quality indicator** for the rep,
not a routing override.

## Feedback loop

**Phase 1 (along with webui)**:
- **Edit-distance comparison** — diff the rep's sent reply against the
  agent's draft. Large diffs signal the draft was unhelpful.
- **Explicit 👍 / 👎** — one-click rating on the draft.

**Phase 2 (later)**:
- **Outcome tracking** — did this thread convert? Did the customer reply
  positively? Tie back to which historical examples / docs the agent cited.
  Promote high-conversion examples in retrieval ranking.

We explicitly **do not** ship without a feedback loop — silent quality
decay is the failure mode that kills tools like this.

## Data freshness

Historical thread corpus is sourced from
`data/processed/hubspot_form_inquiries_long.csv`, ingested via
`scripts/ingest_historical_threads.py`.

- **Phase 1**: daily re-ingest (cron)
- **Phase 2**: hourly, then near-real-time (HubSpot webhook → ingestion
  pipeline) once the daily-update window proves too stale

Re-ingestion is **idempotent** — `_stable_id(metadata)` keys each chunk by
`{submission_id}__{reply_index}`, so adding new rows or correcting
existing ones upserts cleanly.

## Roadmap

Derived from prioritization in the 2026-04-27 alignment session.

### P1 — Demo / now
- Streamlit webui (inbound mode) wrapping `run_email_agent`
- Trust calibration display
- Daily re-ingest cron
- 90% draft quality push: prompt tuning, possibly few-shot examples

### P2 — 1-2 weeks
- **Outbound drafting mode** — sales rep gives a scenario; agent drafts
  outreach. Different input shape, same retrieval corpus.
- **Customer history** — link by `contact_id` / email across past
  threads. When CSR is replying to customer X, surface what X has asked
  before.
- **Multi-language** — locale detection on incoming message; Chinese
  prompt for `_DRAFT_SYSTEM_PROMPT` when locale=zh.
- **Sales style matching** — match current handling rep against historical
  replies they have written; weight their voice in the draft.

### P3 — 1-2 months
- **Attachment parsing** — customer attaches a paper / spec / order PDF;
  agent extracts relevant context.
- **Edit-distance feedback** instrumentation
- **Explicit 👍 / 👎 rating** UI

### P4 — 3 months+
- **Email plugin deployment** — Gmail / Outlook integration replacing the
  standalone webui as the primary entry point.
- **Hourly / near-real-time data sync** — HubSpot webhook listener.
- **Auto-quote** — pricing model trained on historical quote patterns.
- **Outcome tracking feedback loop** (Phase 2 of feedback)

## Frozen / abandoned items

The v4 pivot makes several pre-pivot backlog items moot. They are explicitly
**closed**, not just deferred:

- **Backlog #6 step B** ("flip the confidence gate to handoff") — there is
  no handoff in v4. The tier survives as a quality indicator for the rep.
- **Backlog #9** (`needs_human_contact` flag) — there is no AE handoff to
  trigger. If the customer wants a call, the rep sees that in the draft
  and acts on it.
- **Backlog #10** (multi-intent schema expansion) — the rep sees all
  retrieved content; multi-intent splitting was a customer-facing concern.
- **Backlog #12** (product multi-match clarify routing) — same logic;
  multi-match becomes "show all candidates to rep", which the existing
  retrieval already does.

The seven legacy renderers in `src/responser/renderers/` are dormant.
Cleanup deferred until we are sure no other code imports them.

## Pivot history (v3 → v4)

On 2026-04-27 the project goal shifted. Boss's framing (verbatim):

> *"它能不能把相关历史回复找出来 / 把相关文档找出来 /
> 把这些东西整理成客服可参考的材料"*

The v3 design (a customer-facing reply agent with execute / clarify /
handoff routing) was not abandoned — its mechanical pieces were repurposed
in place. The pivot was implemented through three surgical changes
(documented in §4.1, §4.2, §4.3 above and in the per-module v4 docs):

1. **Tool selection**: both retrieval tools always run as supporting
2. **Routing dispatch**: clarify / handoff coerced to execute, original
   judgment preserved as `AI_ROUTING_NOTE` metadata
3. **Response rendering**: single `render_csr_draft_response` replaces
   the seven mode-specific renderers

`csr_pipeline.py` was briefly built as a parallel pipeline (commit `c7d88a1`)
and then deleted (commit `ab9eeee`) in favor of the in-place pivot. There
is no parallel customer-facing path in v4 — the existing `run_email_agent`
is the only entry point, and it always produces a CSR draft.

## v3 → v2 history (preserved for context)

The original v3 migration from v2 added: typed Pydantic contracts at all
module boundaries, the executor reasoning loop, two-phase memory
(recall/reflect), tool self-description via `ToolCapability`. That work
landed across many commits and is the substrate v4 builds on. Day-to-day
work in v4 should not need to revisit it.

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
