# Architecture

This document summarizes the current target architecture for the v4 CSR / sales co-pilot.

For detailed module designs, see the [reading order](docs/ARCHITECTURE_READING_ORDER.md).

---

## Design Philosophy

The system is an **agent**, not a pipeline. Each turn follows a six-phase loop where the executor autonomously selects tools, observes results, and iterates until it has enough grounded material to produce a rep-facing draft bundle. Adding a new tool requires editing **one file** (the tool's capability declaration); no routing tables or planner mappings need to change.

## Runtime Flow

```
User Message
  1. recall()                       memory: load snapshot, build MemoryContext
  2. build_ingestion_bundle()       ingestion: parse query, extract signals
  3. resolve_objects()              objects: resolve entities from signals
  4. assemble_intent_groups()       ingestion: bind request_flags to objects
  5. build_demand_profile()         ingestion: semantic demand classification
  ── per IntentGroup ──
  6. route()                        routing: classify execute / clarify / respond / handoff
  7. coerce route for CSR mode      non-execute outputs become advisory AI_ROUTING_NOTE metadata
  8. select_tools()                 executor: registry-based tool selection
  9. evaluate_execution_paths()     executor: readiness check (full/degraded/insufficient)
 10. run_executor()                 executor: dispatch → observe → retry loop
  ──────────────────
 11. build_response_bundle()        responser: synthesize csr_draft bundle from all group outcomes
 12. reflect()                      memory: merge contributions, persist snapshot
```

## Module Responsibilities

### ingestion (`src/ingestion/`)

Parses the raw user message into structured signals. Outputs `IngestionBundle` containing:

- **TurnCore**: normalized query, thread_id, attachments
- **ParserSignals**: primary_intent, request_flags, entities, retrieval_hints
- **DeterministicSignals**: rule-based context flags (pricing, technical, etc.)
- **ReferenceSignals**: attachment-derived evidence

Key subsystems:
- **parser_adapter** + **parser_prompt**: LLM-based structured extraction
- **signal_refinement**: non-destructive correction of intent/flag inconsistencies
- **demand_profile**: semantic classification of request_flags into demand types (technical / commercial / operational)
- **intent_assembly** (`src/routing/intent_assembly.py`): deterministic binding of flags to resolved objects via `_FLAG_OBJECT_AFFINITY`, producing `list[IntentGroup]`

### memory (`src/memory/`)

Two-phase lifecycle:

- **recall()**: at turn start. Loads `MemorySnapshot`, builds `MemoryContext` with prior intent groups, continuity confidence, conversation trajectory, clarification state, and object salience scores.
- **reflect()**: at turn end. Merges `MemoryContribution` from each layer (ingestion, objects, routing, response) into updated `MemorySnapshot`, persists to session store.

Key concepts: object salience scoring, intent drift detection, intent group continuity for multi-turn follow-ups.

### objects (`src/objects/`)

Resolves entity spans from parser output into typed `ObjectCandidate` instances. Outputs `ResolvedObjectState` with primary_object, secondary_objects, ambiguous_sets. Independent of routing and execution.

### routing (`src/routing/`)

Determines **what action to take**, not which tools to call. Outputs `RouteDecision`:

```
action: "execute" | "respond" | "clarify" | "handoff"
dialogue_act: DialogueActResult  (inquiry | selection | closing)
clarification: ClarificationPayload | None
reason: str
```

Three dialogue acts (signal-driven, two-level classification):
- **inquiry**: new question or follow-up (default)
- **selection**: user selecting from prior clarification options
- **closing**: conversation wrap-up, no action needed

Action priority: handoff > clarify > closing(respond) > execute.

Routing does **not** select tools. Tool selection moved to executor.

In v4 CSR mode, routing remains a classifier, but its non-`execute` outputs do
not short-circuit retrieval. The agent loop coerces `clarify`, `handoff`, and
`respond` into `execute` and preserves the original judgment as advisory
`AI_ROUTING_NOTE` metadata for the CSR draft.

### executor (`src/executor/`)

Autonomous reasoning loop:

1. **select_tools()** — match ExecutionContext against registry capabilities (demand-aware scoring)
2. **evaluate_execution_paths()** — readiness check per tool (full / degraded / insufficient)
3. **dispatch** — build requests, call tools (with cross-group cache deduplication)
4. **evaluate_completeness()** — sufficient? → done. Insufficient? → retry with fallback (max 3 iterations)

Key contracts:
- `ExecutionContext`: carries query, primary_object, dialogue_act, request_flags, active_demand
- `PathEvaluation`: recommended_action (execute/clarify), executable_paths, blocked_paths
- `ExecutionResult`: executed_calls, merged_results, final_status

Resolution chain: when all paths are insufficient, `find_resolution_provider()` looks for a tool that can provide the missing identifier (one-step only).

### tools (`src/tools/`)

Self-describing capabilities via `ToolCapability`:

- `supported_request_flags`: which flags this tool satisfies
- `supported_object_types`: which object types it handles
- `full_identifiers`: params for precise lookup (API returns unique result)
- `degraded_identifiers`: params for fuzzy lookup (may return multiple)
- `provides_params`: what this tool's results can contribute to other tools

`ToolReadiness` (from `check_readiness()`): three quality levels — full, degraded, insufficient.

Tool families: catalog, documents, rag (technical), quickbooks (customer/order/invoice/shipping).

### responser (`src/responser/`)

Synthesizes the rep-facing draft bundle from execution outcomes:

- **planner**: determines response topic and memory continuity signals
- **blocks**: builds structured `ContentBlock` list from `ExecutionResult` (tagged by source group and demand)
- **renderers**: `csr_draft` is the only renderer dispatched in v4; it produces a structured draft plus references plus routing notes
- **composer**: preserves the structured CSR output format instead of collapsing everything into a customer-facing freeform reply

### agent loop (`src/app/service.py`)

Orchestrates the full turn via `_run_agent_loop()`:

- Iterates over `IntentGroup` list (multi-intent support)
- Per group: compute `GroupDemand` → `route()` → coerce to CSR execute flow → path evaluation → `run_executor()` or path-based clarification advisory
- `ToolCallCache`: cross-group deduplication + observation sharing
- `AgentState`: tracks `GroupOutcome` per group, derives overall action and merged results

## Data Contracts

```
IngestionBundle ─────────────────────> MemoryContext
       │                                    │
       v                                    v
ResolvedObjectState ──> IntentGroup[] ──> DemandProfile
       │                     │                │
       v                     v                v
  RouteDecision ────> ExecutionContext ──> ExecutionResult
       │                                       │
       v                                       v
  ClarificationPayload              GroupOutcome[] ──> ResponseBundle
```

## Capability Layers

| Layer | Modules | Purpose |
|-------|---------|---------|
| catalog | `src/catalog/` | Product/service master data |
| documents | `src/documents/` | Document retrieval (COA, SDS, datasheets) |
| rag | `src/rag/` | Technical knowledge retrieval |
| integrations | `src/integrations/` | External system adapters (QuickBooks) |

## Key Differences From v2

| Aspect | v2 / early v3 | v4 CSR mode |
|--------|----|----|
| Tool selection | Routing decides tools via `tool_routing.py` | Executor reads registry at runtime |
| Adding a tool | Edit 3-4 modules | Edit 1 file (capability declaration) |
| Multi-intent | Single intent, flags ignored | `IntentGroup[]` with per-group routing and execution |
| Dialogue acts | 6 acts including UNKNOWN | 3 acts (inquiry, selection, closing) |
| Clarification | Blocking route outcome | Advisory route outcome + readiness-driven path evaluation |
| Memory | Passive snapshot load | Active recall/reflect with salience and drift detection |
| Response module | `src/response/` | `src/responser/` |
| Modality | Explicit modality classification | Derived from request_flags at tool level |
| Final output | Customer-facing reply variants | Unified CSR-facing `csr_draft` bundle |

## Canonical Vocabulary

| Term | Definition |
|------|-----------|
| IntentGroup | One user need = intent + object + request_flags subset |
| GroupDemand | Semantic demand classification for one IntentGroup |
| DemandProfile | Aggregated demand across all IntentGroups |
| ToolCapability | Self-description of what a tool can do and needs |
| ToolReadiness | Runtime assessment: full / degraded / insufficient |
| PathEvaluation | Readiness check result with execute-or-clarify recommendation |
| RouteDecision | Action + dialogue_act + optional clarification |
| ExecutionContext | All inputs the executor needs for one group |
| GroupOutcome | Result of processing one IntentGroup through route + execute |
