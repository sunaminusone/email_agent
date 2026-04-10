# Code Deprecation Audit

## Goal

This document answers one practical question:

> Which parts of the current codebase should be kept, shrunk, wrapped, replaced, or deleted later as the new architecture lands?

This is **not** a delete-first plan.

It is a transition map.

The purpose is to prevent two kinds of mistakes:

- deleting code that still contains core business logic
- preserving legacy orchestrators long after their responsibilities have moved elsewhere

## Classification Legend

Each module should be classified into one of five buckets:

- `keep`
  - remains a core part of the target architecture
- `shrink`
  - remains, but with a narrower responsibility
- `wrap`
  - keep behavior for now, but place behind a new boundary
- `replace`
  - build a new architecture-native layer and migrate callers away
- `delete later`
  - safe retirement target only after replacement is live and callers are removed

## Important Rule

The audit should be read together with:

- [IMPLEMENTATION_ROADMAP.md](/Users/promab/anaconda_projects/email_agent/docs/IMPLEMENTATION_ROADMAP.md)
- [INGESTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_LAYER_DESIGN.md)
- [OBJECTS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/OBJECTS_LAYER_DESIGN.md)
- [ROUTING_REDESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_REDESIGN.md)

Do **not** delete a module just because it is marked `delete later`.

Deletion should happen only after:

1. the new contract exists
2. runtime traffic has been moved
3. regressions are covered
4. no callers remain

## High-Level Assessment

The current codebase is not "full of dead code".

Most modules still fit into one of these categories:

- valuable domain logic
- useful adapters
- overgrown orchestrators
- legacy boundary glue

So the right move now is:

- preserve domain logic
- shrink orchestration-heavy legacy modules
- wrap old entrypoints behind new contracts
- defer hard deletion until the new architecture is actually live

## Immediate Conclusion

There are **very few safe hard deletions right now**.

The codebase is still actively wired through the legacy flow:

- parser -> agent input -> route decision -> execution plan -> response

So the immediate target is not deletion.

The immediate target is **responsibility reduction**.

## Module Audit

### 1. Parser

#### `keep` or `wrap`

- [service.py](/Users/promab/anaconda_projects/email_agent/src/parser/service.py)
  - very thin adapter
  - should survive as a compatibility wrapper during the ingestion refactor
- [preprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/preprocess.py)
  - keep as ingestion preprocessing logic
- [chain.py](/Users/promab/anaconda_projects/email_agent/src/parser/chain.py)
  - keep as the parser model adapter
- [postprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/postprocess.py)
  - keep, but move conceptually under ingestion signal refinement
- [intent_resolution.py](/Users/promab/anaconda_projects/email_agent/src/parser/intent_resolution.py)
  - keep as parser-side signal enrichment

#### Recommended classification

- `service.py` -> `wrap`
- `preprocess.py` -> `keep`
- `chain.py` -> `keep`
- `postprocess.py` -> `keep`
- `intent_resolution.py` -> `keep`

#### Why

These files are not the problem by themselves.

The issue is that they currently feed directly into legacy `AgentContext` construction instead of a new `IngestionBundle`.

## 2. Conversation / Payload Construction

This is currently one of the most overloaded areas in the codebase.

#### `shrink` / `replace` / `delete later`

- [agent_input_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/agent_input_service.py)
  - currently one of the heaviest legacy assembly points
  - mixes parser enrichment, routing memory, turn resolution, reference resolution, session payload building, effective query construction
  - target state: most of this responsibility should split across `ingestion`, `objects`, and `memory`
  - classification: `replace`

- [payload_builders.py](/Users/promab/anaconda_projects/email_agent/src/conversation/payload_builders.py)
  - currently turns many scattered signals into session and routing payloads
  - some logic is valuable, but the file mixes deterministic payloads, interpreted payloads, session payloads, and active entity shaping
  - classification: `shrink`

- [payload_merge_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/payload_merge_service.py)
  - legacy glue for enriching parsed output with turn/reference resolution
  - likely transitional only once ingestion/object contracts are formalized
  - classification: `wrap`

- [query_resolution.py](/Users/promab/anaconda_projects/email_agent/src/conversation/query_resolution.py)
  - legacy effective/retrieval query shaping
  - likely to be absorbed into ingestion + RAG planning contracts
  - classification: `replace`

- [reference_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/reference_resolution_service.py)
  - keep logic, but split conceptually:
    - ingestion-time referential signal detection
    - object-time referential resolution
  - classification: `wrap`

- [routing_state_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/routing_state_service.py)
  - still useful, but likely becomes part of typed memory adapters
  - classification: `shrink`

- [turn_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/turn_resolution_service.py)
  - contains valuable multi-turn behavior, but should no longer own object or routing semantics
  - classification: `shrink`

- [context_scope.py](/Users/promab/anaconda_projects/email_agent/src/conversation/context_scope.py)
  - classic legacy candidate for retirement
  - useful today, but conceptually replaced by:
    - `ResolvedObjectState`
    - object constraints
    - routing internal act/modality decisions
  - classification: `delete later`

- [service_registry.py](/Users/promab/anaconda_projects/email_agent/src/conversation/service_registry.py)
  - valuable domain registry
  - should migrate conceptually under `objects/registries`
  - classification: `keep`

#### Highest-risk legacy module in this area

- [agent_input_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/agent_input_service.py)

This is a top candidate for staged replacement, not hard deletion.

## 3. Catalog

#### `keep`

- [product_registry.py](/Users/promab/anaconda_projects/email_agent/src/catalog/product_registry.py)
  - core domain asset
  - keep

- [service.py](/Users/promab/anaconda_projects/email_agent/src/catalog/service.py)
  - backend connectivity / service helpers
  - keep, likely behind tool/service adapters

- [retrieval/exact_lookup.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/exact_lookup.py)
- [retrieval/alias_lookup.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/alias_lookup.py)
- [retrieval/fuzzy_lookup.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/fuzzy_lookup.py)
- [retrieval/shared.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/shared.py)
  - keep as retrieval primitives

#### `shrink`

- [selection.py](/Users/promab/anaconda_projects/email_agent/src/catalog/selection.py)
  - major over-responsibility hotspot
  - should narrow to candidate retrieval/scoring/ambiguity grouping only
  - classification: `shrink`

- [normalization.py](/Users/promab/anaconda_projects/email_agent/src/catalog/normalization.py)
  - keep, but scope should tighten around lookup normalization rather than orchestration-like decisions
  - classification: `shrink`

- [ranking.py](/Users/promab/anaconda_projects/email_agent/src/catalog/ranking.py)
  - keep, but only as ranking/scoring logic
  - classification: `shrink`

#### Delete-later candidates

There are no immediate hard-delete candidates in catalog.

The right move is to shrink [selection.py](/Users/promab/anaconda_projects/email_agent/src/catalog/selection.py), not remove the catalog stack.

## 4. Decision / Routing

This is another overloaded area.

#### `replace` / `shrink`

- [route_decision_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_decision_service.py)
  - current legacy router entrypoint
  - mixes rule overrides, prompt routing, business-line reasoning, and world-selection logic
  - classification: `replace`

- [route_preconditions.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_preconditions.py)
  - contains useful guards, but too much architecture logic currently leaks here
  - should survive only as narrow guardrail logic
  - classification: `shrink`

- [commercial_route_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/commercial_route_policy.py)
- [operational_route_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/operational_route_policy.py)
- [workflow_route_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/workflow_route_policy.py)
  - useful decision heuristics
  - but current shape is still route-world centric
  - classification: `shrink`

- [route_policy_shared.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_policy_shared.py)
  - likely transitional utility layer
  - classification: `delete later`

- [routing_prompt.py](/Users/promab/anaconda_projects/email_agent/src/decision/routing_prompt.py)
  - likely either shrinks drastically or becomes obsolete once routing is more deterministic and object-centric
  - classification: `delete later`

#### `keep`

- [response_resolution/dialogue_act.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_resolution/dialogue_act.py)
  - the logic belongs conceptually in routing
  - the module itself likely survives, though it should move or be rehomed later
  - classification: `keep`

#### `shrink`

- [response_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_service.py)
  - still useful as a handoff point into response generation
  - should narrow once response becomes fully `ExecutionRun`-driven
  - classification: `shrink`

## 5. Orchestration

#### `replace`

- [prototype_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/prototype_service.py)
  - currently the biggest legacy super-orchestrator
  - it does parsing, session loading, route-state persistence, plan execution, and response wiring
  - classification: `replace`

#### `shrink`

- [planner_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/planner_service.py)
  - valuable conceptually, but currently tied to old `RouteDecision` / action enums
  - classification: `shrink`

- [executor_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/executor_service.py)
  - valuable conceptually, but currently dispatches through old route/action shapes
  - classification: `shrink`

## 6. Tools

#### `keep`

- [catalog_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/catalog_tools.py)
- [rag_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/rag_tools.py)
- [order_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/order_lookup.py)
- [invoice_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/invoice_lookup.py)
- [shipping_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/shipping_lookup.py)
- [customer_lookup.py](/Users/promab/anaconda_projects/email_agent/src/tools/customer_lookup.py)
- [quickbooks_tool_helper.py](/Users/promab/anaconda_projects/email_agent/src/tools/quickbooks_tool_helper.py)
- [action_utils.py](/Users/promab/anaconda_projects/email_agent/src/tools/action_utils.py)
- [shipping_utils.py](/Users/promab/anaconda_projects/email_agent/src/tools/shipping_utils.py)

These should mostly survive.

The main change is not deletion.

The main change is:

- wrap them behind `ToolRequest` / `ToolResult`
- stop letting upstream routing assumptions leak into them

#### Recommended classification

- mostly `keep`
- some helper files may later `shrink`

## 7. RAG

#### `keep`

- [service.py](/Users/promab/anaconda_projects/email_agent/src/rag/service.py)
- [retriever.py](/Users/promab/anaconda_projects/email_agent/src/rag/retriever.py)
- [reranker.py](/Users/promab/anaconda_projects/email_agent/src/rag/reranker.py)
- [service_page_ingestion.py](/Users/promab/anaconda_projects/email_agent/src/rag/service_page_ingestion.py)
- [vectorstore.py](/Users/promab/anaconda_projects/email_agent/src/rag/vectorstore.py)
- [ingestion_config.py](/Users/promab/anaconda_projects/email_agent/src/rag/ingestion_config.py)

These are core tool-family assets.

They should not be deleted.

They should instead be:

- consumed via tool contracts
- progressively detached from legacy scope-only assumptions

## 8. Memory

#### `keep`

- [session_store.py](/Users/promab/anaconda_projects/email_agent/src/memory/session_store.py)

This should remain the persistence adapter.

What changes is not whether it exists.

What changes is the structure of what gets stored and loaded.

#### `replace later`

The current loose `route_state` payload semantics should eventually be replaced by typed memory contracts, but that does **not** imply deleting the store itself.

## 9. Response

#### `keep`

- [response/chain.py](/Users/promab/anaconda_projects/email_agent/src/response/chain.py)
- [response/content/blocks.py](/Users/promab/anaconda_projects/email_agent/src/response/content/blocks.py)
- [response/content/builder.py](/Users/promab/anaconda_projects/email_agent/src/response/content/builder.py)
- [response/content/clarification.py](/Users/promab/anaconda_projects/email_agent/src/response/content/clarification.py)
- [response/preprocess.py](/Users/promab/anaconda_projects/email_agent/src/response/preprocess.py)
- [response/postprocess.py](/Users/promab/anaconda_projects/email_agent/src/response/postprocess.py)
- [response/prompt.py](/Users/promab/anaconda_projects/email_agent/src/response/prompt.py)

#### `shrink`

- [decision/response_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_service.py)
  - should become thinner as the dedicated response layer takes over

#### `delete later`

- [responders/legacy_fallback.py](/Users/promab/anaconda_projects/email_agent/src/responders/legacy_fallback.py)
  - strong candidate for eventual retirement once response coverage is complete and legacy responder fallback is no longer needed

The goal here is not to delete the response pipeline.

The goal is to retire legacy fallback branches once the new grounded pipeline is fully covering the same cases.

## 10. Schemas

This directory is not yet a delete target.

But it is a likely future split point.

#### `replace gradually`

- [agent_context_schema.py](/Users/promab/anaconda_projects/email_agent/src/schemas/agent_context_schema.py)
- [routing_schema.py](/Users/promab/anaconda_projects/email_agent/src/schemas/routing_schema.py)
- [plan_schema.py](/Users/promab/anaconda_projects/email_agent/src/schemas/plan_schema.py)
- [runtime_context_schema.py](/Users/promab/anaconda_projects/email_agent/src/schemas/runtime_context_schema.py)

These likely survive only temporarily while new:

- ingestion contracts
- object contracts
- tool contracts
- execution contracts
- response contracts

become dominant.

So this family is mostly `replace gradually`, not `delete now`.

## No Safe Immediate Deletions

At this moment, the following modules should **not** be hard-deleted yet even if they are legacy-shaped:

- [agent_input_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/agent_input_service.py)
- [context_scope.py](/Users/promab/anaconda_projects/email_agent/src/conversation/context_scope.py)
- [route_decision_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_decision_service.py)
- [planner_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/planner_service.py)
- [executor_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/executor_service.py)
- [prototype_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/prototype_service.py)
- [selection.py](/Users/promab/anaconda_projects/email_agent/src/catalog/selection.py)

These are all critical legacy spine modules.

They should be replaced or shrunk through staged migration, not removed abruptly.

## Best Early Delete-Later Candidates

These are the strongest future retirement candidates once the new architecture is live:

- [context_scope.py](/Users/promab/anaconda_projects/email_agent/src/conversation/context_scope.py)
- [route_policy_shared.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_policy_shared.py)
- [routing_prompt.py](/Users/promab/anaconda_projects/email_agent/src/decision/routing_prompt.py)
- [responders/legacy_fallback.py](/Users/promab/anaconda_projects/email_agent/src/responders/legacy_fallback.py)

These are not immediate deletions.

They are the clearest long-term retirement targets.

## Best Early Shrink Targets

If the goal is to reduce architectural drag quickly, the best early shrink targets are:

1. [selection.py](/Users/promab/anaconda_projects/email_agent/src/catalog/selection.py)
2. [agent_input_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/agent_input_service.py)
3. [route_decision_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_decision_service.py)
4. [payload_builders.py](/Users/promab/anaconda_projects/email_agent/src/conversation/payload_builders.py)
5. [prototype_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/prototype_service.py)

These are the modules currently carrying the most legacy architectural burden.

## Suggested Next Step

Before deleting anything, build one migration table with these columns:

- module
- current responsibility
- target layer
- target classification
- replacement contract
- safe deletion condition

This should become the working checklist for the implementation roadmap.

## Summary

The codebase should not be approached as:

- "what can we delete first?"

It should be approached as:

- "what should remain core?"
- "what should shrink?"
- "what should be wrapped behind new boundaries?"
- "what becomes unnecessary after migration?"

Right now, the strongest move is:

- shrink orchestration-heavy legacy modules
- preserve domain logic
- defer hard deletion until the new contracts are actually live
