# Architecture Reading Order

This document is the entrypoint for the current design set.

## Current Architecture Version: v3

The v3 architecture introduces an agent-based design with autonomous tool selection and a reasoning loop in the executor.

The primary design document is:

- [AGENT_ARCHITECTURE_V3.md](AGENT_ARCHITECTURE_V3.md)

## Recommended Reading Order

1. [AGENT_ARCHITECTURE_V3.md](AGENT_ARCHITECTURE_V3.md) — **start here**: overall agent architecture, module responsibilities, data contracts, migration path
2. [INGESTION_DESIGN_V3.md](INGESTION_DESIGN_V3.md) — signal extraction, parser adapter, deterministic/reference signals
3. [MEMORY_DESIGN_V3.md](MEMORY_DESIGN_V3.md) — two-phase recall/reflect lifecycle, salience scoring, intent drift detection
4. [ROUTING_DESIGN_V3.md](ROUTING_DESIGN_V3.md) — route decision with execution intent
5. [EXECUTOR_DESIGN_V3.md](EXECUTOR_DESIGN_V3.md) — reasoning loop, tool dispatch, observation
6. [TOOLS_DESIGN_V3.md](TOOLS_DESIGN_V3.md) — self-describing capability contracts

## Responsibility Matrix (v3)

| Document | Responsibility | Input | Output |
| --- | --- | --- | --- |
| [AGENT_ARCHITECTURE_V3.md](AGENT_ARCHITECTURE_V3.md) | Overall agent design, module boundaries, data flow | — | Architecture contracts |
| [INGESTION_DESIGN_V3.md](INGESTION_DESIGN_V3.md) | Parse and normalize turn evidence | Raw turn, prior state | `IngestionBundle` |
| [MEMORY_DESIGN_V3.md](MEMORY_DESIGN_V3.md) | Two-phase memory lifecycle (recall/reflect), salience, intent drift | `MemorySnapshot` | `MemoryContext`, `MemoryContribution` |
| [ROUTING_DESIGN_V3.md](ROUTING_DESIGN_V3.md) | Route decision: execute / clarify / handoff | `IngestionBundle`, `ResolvedObjectState` | `RouteDecision` |
| [EXECUTOR_DESIGN_V3.md](EXECUTOR_DESIGN_V3.md) | Reasoning loop with tool dispatch and observation | `ExecutionIntent` | `ExecutionRun` |
| [TOOLS_DESIGN_V3.md](TOOLS_DESIGN_V3.md) | Self-describing tool capabilities | `ToolRequest` | `ToolResult` |

## v3 Data Flow

```
User Message + Memory
  -> recall()                   (memory: load + contextualize)
  -> IngestionBundle            (ingestion: parse + extract signals)
  -> ResolvedObjectState        (objects: resolve entities)
  -> RouteDecision              (routing: execute / clarify / handoff)
  -> ExecutionRun               (executor: reason + dispatch tools + observe loop)
  -> ResponseBundle             (responser: synthesize reply)
  -> reflect()                  (memory: merge contributions + persist)
```
