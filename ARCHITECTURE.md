# Architecture

This project is a modular biotech support agent built around typed Python services plus LangChain at the LLM boundaries.

The guiding principle is:

- LangChain handles parsing, routing LLM fallback, and response generation boundaries.
- Typed Python modules handle state, business rules, data access, and tool execution.

## High-Level Runtime Flow

```text
user input
  -> parser
  -> conversation
  -> context
  -> decision
  -> orchestration
  -> tools / integrations / data capabilities
  -> response
  -> final assistant message
```

In more concrete terms:

1. `parser/` converts the current turn into `ParsedResult`.
2. `conversation/` combines `ParsedResult` with session state and produces `AgentContext`.
3. `context/` assembles `RuntimeContext` for downstream routing and execution.
4. `decision/` decides route and response strategy.
5. `orchestration/` plans and executes the selected actions.
6. `response/` builds grounded content and renders the final answer.

## Module Boundaries

### `src/orchestration/`

Shared lifecycle and execution ordering.

This layer answers:
- What runs next?
- In what order do parse, route, plan, execute, and respond happen?

Current files:
- [prototype_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/prototype_service.py)
- [planner_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/planner_service.py)
- [executor_service.py](/Users/promab/anaconda_projects/email_agent/src/orchestration/executor_service.py)

This layer should not own:
- business rules
- route heuristics
- storage logic
- external API details

### `src/parser/`

Current-turn understanding only.

This layer answers:
- What does this single user turn mean on its own?

Output:
- `ParsedResult`

Current structure:
- [service.py](/Users/promab/anaconda_projects/email_agent/src/parser/service.py)
- [chain.py](/Users/promab/anaconda_projects/email_agent/src/parser/chain.py)
- [prompt.py](/Users/promab/anaconda_projects/email_agent/src/parser/prompt.py)
- [preprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/preprocess.py)
- [postprocess.py](/Users/promab/anaconda_projects/email_agent/src/parser/postprocess.py)
- [intent_resolution.py](/Users/promab/anaconda_projects/email_agent/src/parser/intent_resolution.py)

Parser is implemented as an LCEL-style pipeline:

```text
preprocess -> prompt -> structured LLM -> postprocess
```

### `src/conversation/`

Multi-turn conversation interpretation.

This layer answers:
- Is this a new request or follow-up?
- Should prior payload be reused?
- What does `this one` refer to?
- What should the effective query be?

Output:
- `AgentContext`

Current structure:
- [agent_input_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/agent_input_service.py)
- [turn_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/turn_resolution_service.py)
- [reference_resolution_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/reference_resolution_service.py)
- [routing_state_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/routing_state_service.py)
- [payload_builders.py](/Users/promab/anaconda_projects/email_agent/src/conversation/payload_builders.py)
- [payload_merge_service.py](/Users/promab/anaconda_projects/email_agent/src/conversation/payload_merge_service.py)
- [query_resolution.py](/Users/promab/anaconda_projects/email_agent/src/conversation/query_resolution.py)

### `src/context/`

Runtime context assembly.

This layer answers:
- What external/runtime context should the downstream system see?

Current structure:
- [context_provider.py](/Users/promab/anaconda_projects/email_agent/src/context/context_provider.py)
- [providers.py](/Users/promab/anaconda_projects/email_agent/src/context/providers.py)
- [formatter.py](/Users/promab/anaconda_projects/email_agent/src/context/formatter.py)

Responsibilities:
- combine memory, history, retrieval, and preferences
- build prompt-ready sections for route and response stages

### `src/memory/`

Session persistence.

This layer answers:
- What should be remembered across turns?

Current structure:
- [session_store.py](/Users/promab/anaconda_projects/email_agent/src/memory/session_store.py)

Responsibilities:
- Redis-backed state by `thread_id`
- persisted route state
- persisted session payload
- bounded recent history

### `src/decision/`

System decisions, not execution.

This layer answers:
- Which route should handle this turn?
- What kind of answer should be produced?

Current structure:
- [route_decision_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_decision_service.py)
- [commercial_route_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/commercial_route_policy.py)
- [operational_route_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/operational_route_policy.py)
- [workflow_route_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/workflow_route_policy.py)
- [route_preconditions.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_preconditions.py)
- [route_policy_shared.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_policy_shared.py)
- [routing_prompt.py](/Users/promab/anaconda_projects/email_agent/src/decision/routing_prompt.py)
- [response_service.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_service.py)

#### `src/decision/response_resolution/`

This is the response-strategy submodule.

It answers:
- What response topic is this?
- What is the answer focus?
- What style should be used?
- Which fields should appear, and in what order?

Current structure:
- [service.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_resolution/service.py)
- [topic_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_resolution/topic_policy.py)
- [focus_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_resolution/focus_policy.py)
- [style_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_resolution/style_policy.py)
- [content_policy.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_resolution/content_policy.py)
- [common.py](/Users/promab/anaconda_projects/email_agent/src/decision/response_resolution/common.py)

The `service.py` file is intentionally thin. The actual policy logic lives in the topic/focus/style/content submodules.

### Data and Capability Layers

These modules answer factual questions. They are not orchestration layers.

#### `src/catalog/`

Structured product lookup.

Responsibilities:
- candidate retrieval
- result ranking
- final selection
- service-level lookup interface
- business line normalization

Current structure:
- [retrieval](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval)
- [ranking.py](/Users/promab/anaconda_projects/email_agent/src/catalog/ranking.py)
- [selection.py](/Users/promab/anaconda_projects/email_agent/src/catalog/selection.py)
- [normalization.py](/Users/promab/anaconda_projects/email_agent/src/catalog/normalization.py)
- [service.py](/Users/promab/anaconda_projects/email_agent/src/catalog/service.py)

Inside `retrieval/`:
- [shared.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/shared.py)
- [exact_lookup.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/exact_lookup.py)
- [alias_lookup.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/alias_lookup.py)
- [fuzzy_lookup.py](/Users/promab/anaconda_projects/email_agent/src/catalog/retrieval/fuzzy_lookup.py)

The intended flow is:

```text
normalize -> retrieval -> ranking -> selection -> service
```

#### `src/documents/`

Structured document metadata and file matching.

Responsibilities:
- inventory retrieval
- document-type and business-line normalization
- result ranking
- final selection
- service-level lookup interface

Current structure:
- [retrieval](/Users/promab/anaconda_projects/email_agent/src/documents/retrieval)
- [ranking.py](/Users/promab/anaconda_projects/email_agent/src/documents/ranking.py)
- [selection.py](/Users/promab/anaconda_projects/email_agent/src/documents/selection.py)
- [normalization.py](/Users/promab/anaconda_projects/email_agent/src/documents/normalization.py)
- [service.py](/Users/promab/anaconda_projects/email_agent/src/documents/service.py)

Inside `retrieval/`:
- [shared.py](/Users/promab/anaconda_projects/email_agent/src/documents/retrieval/shared.py)

This layer reads:
- `document_catalog.csv`
- local PDF inventory under `data/raw/pdf`

The intended flow is:

```text
normalize -> retrieval -> ranking -> selection -> service
```

#### `src/rag/`

Semantic technical retrieval.

Responsibilities:
- vector store loading
- chunk retrieval
- technical knowledge grounding

Current structure:
- [service.py](/Users/promab/anaconda_projects/email_agent/src/rag/service.py)
- [retriever.py](/Users/promab/anaconda_projects/email_agent/src/rag/retriever.py)
- [vectorstore.py](/Users/promab/anaconda_projects/email_agent/src/rag/vectorstore.py)

#### `src/integrations/`

Low-level external connectors.

Current focus:
- QuickBooks

QuickBooks structure:
- [auth.py](/Users/promab/anaconda_projects/email_agent/src/integrations/quickbooks/auth.py)
- [repository.py](/Users/promab/anaconda_projects/email_agent/src/integrations/quickbooks/repository.py)
- [matching.py](/Users/promab/anaconda_projects/email_agent/src/integrations/quickbooks/matching.py)
- [service.py](/Users/promab/anaconda_projects/email_agent/src/integrations/quickbooks/service.py)

Boundary rule:
- `integrations/` owns clients/connectors
- `tools/` owns LLM-callable actions built on top of them

### `src/tools/`

Atomic actions callable by the agent layer.

Examples:
- catalog lookup
- document lookup
- technical retrieval
- customer lookup
- invoice lookup
- order lookup
- shipping lookup

These tools should call into:
- `catalog/`
- `documents/`
- `rag/`
- `integrations/`

but should not own low-level connector logic themselves.

### `src/agents/`

Domain-role implementations.

This layer answers:
- If a route selects a domain agent, which concrete tool sequence should that agent run?

Current files:
- [commercial_agent.py](/Users/promab/anaconda_projects/email_agent/src/agents/commercial_agent.py)
- [operational_agent.py](/Users/promab/anaconda_projects/email_agent/src/agents/operational_agent.py)
- [workflow_agent.py](/Users/promab/anaconda_projects/email_agent/src/agents/workflow_agent.py)
- [constants.py](/Users/promab/anaconda_projects/email_agent/src/agents/constants.py)
- [selector.py](/Users/promab/anaconda_projects/email_agent/src/agents/selector.py)
- [utils.py](/Users/promab/anaconda_projects/email_agent/src/agents/utils.py)

Boundary rule:
- `agents/` owns domain role behavior
- `orchestration/` owns the shared lifecycle

### `src/response/`

Final response construction.

This layer answers:
- Given route, execution results, and response strategy, what grounded content should be assembled?
- Which response path should be used: deterministic, renderer, legacy fallback, or LLM chain?

Current files:
- [chain.py](/Users/promab/anaconda_projects/email_agent/src/response/chain.py)
- [preprocess.py](/Users/promab/anaconda_projects/email_agent/src/response/preprocess.py)
- [prompt.py](/Users/promab/anaconda_projects/email_agent/src/response/prompt.py)
- [postprocess.py](/Users/promab/anaconda_projects/email_agent/src/response/postprocess.py)

#### `src/response/content/`

This is the content-building submodule.

Responsibilities:
- build atomic content blocks
- build deterministic clarification/handoff responses
- resolve legacy fallback
- assemble response-content payload

Current structure:
- [builder.py](/Users/promab/anaconda_projects/email_agent/src/response/content/builder.py)
- [blocks.py](/Users/promab/anaconda_projects/email_agent/src/response/content/blocks.py)
- [clarification.py](/Users/promab/anaconda_projects/email_agent/src/response/content/clarification.py)
- [fallback.py](/Users/promab/anaconda_projects/email_agent/src/response/content/fallback.py)

### `src/responders/`

Rendering layer.

The project currently uses a hybrid model:
- new renderers for topic-based response rendering
- limited legacy fallback for old summary responders

#### New renderers

Located in:
- [renderers](/Users/promab/anaconda_projects/email_agent/src/responders/renderers)

Current topic coverage:
- commercial quote
- product info
- document delivery
- technical doc
- workflow status
- operational status

#### Legacy fallback

Located in:
- [legacy_fallback.py](/Users/promab/anaconda_projects/email_agent/src/responders/legacy_fallback.py)
- [legacy](/Users/promab/anaconda_projects/email_agent/src/responders/legacy)

Current intent:
- keep only minimal summary fallback
- continue shrinking legacy usage over time

## Response Pipeline

The response stack is intentionally layered:

```text
response_resolution(topic/style/focus)
  -> content builder
  -> topic-based renderer
  -> legacy fallback if needed
  -> LLM response chain if needed
  -> postprocess
```

More concretely:

1. `decision/response_resolution/` decides:
   - topic
   - focus
   - style
   - content policy
2. `response/content/` builds:
   - atomic content blocks
   - clarification/handoff responses
   - legacy fallback candidate
3. `responders/renderers/` tries a typed renderer for the topic
4. if no renderer is available, legacy fallback may be used
5. if still unresolved, the LLM response chain is used

## Conversation and Memory Relationship

These layers are related but intentionally separate:

- `memory/` stores session state
- `context/` assembles runtime context
- `conversation/` consumes that state for multi-turn interpretation

This means:
- `memory` remembers
- `context` assembles
- `conversation` interprets

## Architectural Conventions

These boundaries should remain stable:

- `parser/` understands a single turn only.
- `conversation/` handles cross-turn continuity.
- `decision/` decides route and response strategy.
- `orchestration/` executes the runtime lifecycle.
- `catalog/`, `documents/`, `rag/`, and `integrations/` are capability layers.
- `integrations/` contains connectors; `tools/` contains LLM-callable actions.
- `agents/` contains domain-role implementations; `orchestration/` contains the shared lifecycle.
- `responders/renderers/` should focus on expression, not business decision-making.

## Current Testing Baseline

Current regression suite:

```bash
pytest -q tests/test_turn_resolution_regression.py tests/test_response_generation_regression.py
```

This suite currently validates:
- turn resolution
- reference reuse
- response focus selection
- renderer coverage for key topics
- workflow and operational response behavior

## Known Next-Step Opportunities

If the project continues evolving, the next high-value improvements are:

1. expand regression coverage for:
   - parser
   - route decisions
   - catalog retrieval/ranking/selection
   - document retrieval/ranking/selection
   - QuickBooks operational flows
2. continue shrinking legacy responder fallback
3. further split any growing hot files such as:
   - `catalog/repository.py`
   - `conversation/payload_builders.py`
   - `conversation/payload_merge_service.py`
