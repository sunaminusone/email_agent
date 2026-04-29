# Architecture Reading Order

This document is the entrypoint for the v4 design set.

## Current Architecture Version: v4 (post-2026-04-27 pivot)

The v4 architecture is the v3 agent-based design (typed contracts, agent
loop, two-phase memory, self-describing tools) repurposed for a CSR /
sales co-pilot product:

> **An internal email co-pilot for ProMab's customer-service reps and
> sales reps. It generates reviewable, high-quality email drafts based on
> similar past replies, relevant documents, and customer context. It is
> not an autonomous customer-facing reply bot.**

The mechanical v3 substrate carries over; what changed is the consumer
of the output (the rep, not the customer), the output shape (draft +
references, not polished customer reply), and routing semantics
(clarify / handoff are advisory metadata, not gates).

The primary design document is:

- [AGENT_ARCHITECTURE_V4.md](AGENT_ARCHITECTURE_V4.md)

## Recommended Reading Order

1. **[AGENT_ARCHITECTURE_V4.md](AGENT_ARCHITECTURE_V4.md)** — start here. Identity, system use, architecture diagram, module map, three v4 invariants (tool selection / routing dispatch / response rendering), trust calibration, feedback, roadmap, frozen items, pivot history.
2. [INGESTION_DESIGN_V4.md](INGESTION_DESIGN_V4.md) — signal extraction, parser adapter, deterministic/reference signals (reused unchanged from v3)
3. [MEMORY_DESIGN_V4.md](MEMORY_DESIGN_V4.md) — two-phase recall/reflect lifecycle, salience scoring, intent drift detection (reused unchanged from v3)
4. [ROUTING_DESIGN_V4.md](ROUTING_DESIGN_V4.md) — classification still runs as designed; clarify/handoff are advisory in v4
5. [EXECUTOR_DESIGN_V4.md](EXECUTOR_DESIGN_V4.md) — reasoning loop + tool dispatch; v4 adds the always-include rule for retrieval tools
6. [TOOL_CONTRACT_DESIGN_V4.md](TOOL_CONTRACT_DESIGN_V4.md) — tool contracts (v3 framework reused; new `historical_thread_tool` registers via the same API)
7. [PARSER_HELDOUT_SCHEMA_V4.md](PARSER_HELDOUT_SCHEMA_V4.md) — parser benchmark schema (v3 reused; field roles reinterpreted for v4)

## Responsibility Matrix (v4)

| Document | Responsibility | Input | Output |
| --- | --- | --- | --- |
| [AGENT_ARCHITECTURE_V4.md](AGENT_ARCHITECTURE_V4.md) | v4 product identity, module boundaries, data flow, three CSR-mode invariants | — | Architecture contracts |
| [INGESTION_DESIGN_V4.md](INGESTION_DESIGN_V4.md) | Parse and normalize turn evidence | Raw incoming inquiry, prior state | `IngestionBundle` |
| [MEMORY_DESIGN_V4.md](MEMORY_DESIGN_V4.md) | Two-phase memory lifecycle (recall/reflect), salience, intent drift | `MemorySnapshot` | `MemoryContext`, `MemoryContribution` |
| [ROUTING_DESIGN_V4.md](ROUTING_DESIGN_V4.md) | Classify posture (execute/clarify/handoff/respond); in v4 all are coerced to execute, original judgment becomes `AI_ROUTING_NOTE` metadata | `IngestionBundle`, `ResolvedObjectState` | `RouteDecision` |
| [EXECUTOR_DESIGN_V4.md](EXECUTOR_DESIGN_V4.md) | Reasoning loop with tool dispatch and observation; v4 always-includes both retrieval tools | `ExecutionContext` | `ExecutionResult` |
| [TOOL_CONTRACT_DESIGN_V4.md](TOOL_CONTRACT_DESIGN_V4.md) | Tool contracts, readiness evaluation; v3 framework reused for `historical_thread_tool` | `ToolCapability` + `ExecutionContext` | `ToolReadiness`, `PathEvaluation` |
| [PARSER_HELDOUT_SCHEMA_V4.md](PARSER_HELDOUT_SCHEMA_V4.md) | Held-out benchmark schema for parser evaluation | held-out CSV | parser eval metrics |

## v4 Data Flow

```
Incoming inquiry + Memory
  -> recall()                   (memory: load + contextualize)
  -> IngestionBundle            (ingestion: parse + extract signals)
  -> ResolvedObjectState        (objects: resolve entities)
  -> RouteDecision              (routing: classify; v4 coerces to execute,
                                            preserves original on .reason)
  -> ExecutionResult             (executor: dispatch tools — historical_thread_tool
                                            + technical_rag_tool always run)
  -> ResponseBundle             (responser: render_csr_draft_response —
                                            Slack-style draft + references +
                                            ⚠️ AI routing notes)
  -> reflect()                  (memory: merge contributions + persist)
                                            ↓
                              CSR-facing draft bundle
                              (the rep reviews, edits, decides whether to send)
```

## Glossary

- **CSR mode** / **v4** — current architecture; agent's consumer is the
  rep, output is internal draft + references
- **AI_ROUTING_NOTE** — string format on `route_decision.reason` carrying
  original clarify / handoff judgment when action was coerced to execute
- **csr_draft renderer** — `src/responser/renderers/csr_draft.py`; the
  only renderer dispatched in v4
- **historical_threads_v1** — chromadb collection of 8.8k HubSpot sales
  reply units, ingested from `data/processed/hubspot_form_inquiries_long.csv`
- **always-include rule** — v4 invariant in `select_tools` that adds both
  retrieval tools as supporting selections regardless of demand classification
