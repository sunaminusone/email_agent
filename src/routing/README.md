# Routing Package

This package is organized around the routing redesign:

1. `objects` resolves object state upstream and hands `ResolvedObjectState` into routing.
2. `routing` interprets that state through layered internal stages.
3. `routing` emits one compact `ExecutionIntent`.

## Structure

- `models.py`
  - canonical routing contracts
- `vocabulary.py`
  - normalized enums, tool names, and routing vocab
- `utils.py`
  - low-level text normalization helpers
- `stages/`
  - internal layered routing implementation
  - `object_routing.py`
  - `dialogue_act.py`
  - `modality.py`
  - `tool_routing.py`
- `policies/`
  - internal routing helpers for clarification, handoff, and answer-shaping decisions
  - `clarification.py`
  - `handoff.py`
  - `assembly.py`
- `orchestrator.py`
  - composes internal routing steps into one `RoutingDecision`
- `runtime.py`
  - thin boundary helpers that project from `IngestionBundle` plus `ResolvedObjectState`

## Intended Layer Order

`IngestionBundle`
-> `ResolvedObjectState`
-> `RoutingInput`
-> `RoutingDecision`
-> `ExecutionIntent`

The supported construction path is:

- `IngestionBundle` + `ResolvedObjectState` -> `RoutingInput`
- `RoutingInput` -> `RoutingDecision`
- `RoutingDecision` -> `ExecutionIntent`

Direct object-state-only runtime entry points are intentionally not provided.

## Design Intent

- routing does not perform ingestion
- routing does not perform object extraction
- routing does not rediscover object state from storage
- routing does internally resolve dialogue act, modality, and tool choice
- routing may internally decide clarification or handoff before emitting the final routing output
- routing publicly exposes only `RoutingDecision` and `ExecutionIntent`
