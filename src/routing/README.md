# Routing Package

Routing interprets ingestion signals and resolved object state to produce
a `RouteDecision` — the single output contract that tells downstream layers
what action to take (execute, clarify, handoff, or respond).

## Structure

- `models.py` — canonical routing contracts (`RouteDecision`, `DialogueActResult`, etc.)
- `intent_assembly.py` — deterministic binding of request flags to resolved objects → `IntentGroup`
- `stages/` — internal layered routing implementation
  - `dialogue_act.py` — signal-driven dialogue act classification
- `policies/` — routing helpers for clarification, handoff, and answer-shaping decisions
  - `clarification.py`
  - `handoff.py`
- `orchestrator.py` — composes internal routing steps into one `RouteDecision`
- `runtime.py` — convenience entry point (`route_single_group`) for tests and standalone use

## Intended Layer Order

`IngestionBundle` + `ResolvedObjectState`
-> `IntentGroup` + `DemandProfile`
-> `RouteDecision`

## Design Intent

- Routing does not perform ingestion
- Routing does not perform object extraction
- Routing does internally resolve dialogue act and action choice
- Routing may internally decide clarification or handoff before emitting the final output
- Routing publicly exposes `RouteDecision` via `route()` / `route_single_group()`
