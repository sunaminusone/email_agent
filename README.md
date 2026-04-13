# Email Agent

A modular biotech support agent built around typed Python layers plus LLM boundaries.

The current canonical architecture is:

`ingestion -> objects -> routing -> execution -> response`

For the full design set and reading order, start with [docs/ARCHITECTURE_READING_ORDER.md](/Users/promab/anaconda_projects/email_agent/docs/ARCHITECTURE_READING_ORDER.md).

## Project Layout

```text
src/
  app/           # top-level runtime entrypoint and API-facing assembly
  ingestion/     # normalize the current turn into IngestionBundle
  objects/       # resolve products, services, and operational objects
  routing/       # resolve dialogue act, modality, and tool selection
  execution/     # plan and run tool calls from ExecutionIntent
  response/      # compose grounded user-facing replies
  memory/        # typed reusable cross-turn state and persistence
  tools/         # tool contracts, registry, dispatch, and tool implementations
  catalog/       # structured product lookup capability
  documents/     # structured document lookup capability
  rag/           # semantic technical retrieval capability
  integrations/  # external system connectors
  common/        # shared models reused across layers
  config/        # runtime settings and configuration
  strategies/    # reusable deterministic heuristics
```

## Runtime Flow

1. `ingestion/` gathers turn evidence and emits `IngestionBundle`.
2. `objects/` consumes that bundle and emits `ResolvedObjectState`.
3. `routing/` resolves dialogue act, modality, clarification or handoff, and emits `ExecutionIntent`.
4. `execution/` turns that intent into an `ExecutionPlan`, runs tool calls, and returns `ExecutionRun`.
5. `response/` turns grounded execution output plus response memory into the final reply.
6. `memory/` persists typed state updates for the next turn.

The runtime entrypoint in [src/app/service.py](/Users/promab/anaconda_projects/email_agent/src/app/service.py) follows this exact sequence.

## Layer Boundaries

- `ingestion/` does not resolve primary objects or choose tools.
- `objects/` does not execute retrieval or choose tools.
- `routing/` does not perform ingestion or object extraction.
- `execution/` does not re-derive routing decisions or generate the final reply.
- `response/` does not choose tools or perform object resolution.
- `tools/` expose capability contracts; `execution/` is the orchestration layer that calls them.

## Core Contracts

- `IngestionBundle`
- `ResolvedObjectState`
- `DialogueActResult`
- `ModalityDecision`
- `ExecutionIntent`
- `ExecutionPlan`
- `ExecutionRun`
- `MemorySnapshot`
- `MemoryUpdate`
- `ComposedResponse`

## Capabilities

- `catalog/`: structured product and pricing lookup
- `documents/`: document metadata lookup over local inventories
- `rag/`: semantic technical retrieval over curated service-page corpora
- `tools/quickbooks/`: customer, invoice, order, and shipping lookups

## Memory

- Redis-backed session persistence keyed by `thread_id`
- typed thread, object, clarification, and response memory
- `stateful_anchors` reused by ingestion for safe follow-up handling

## Canonical Docs

- architecture entrypoint: [docs/ARCHITECTURE_READING_ORDER.md](/Users/promab/anaconda_projects/email_agent/docs/ARCHITECTURE_READING_ORDER.md)
- ingestion: [docs/INGESTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_LAYER_DESIGN.md)
- objects: [docs/OBJECTS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/OBJECTS_LAYER_DESIGN.md)
- routing: [docs/ROUTING_REDESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_REDESIGN.md)
- tools: [docs/TOOLS_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/TOOLS_LAYER_DESIGN.md)
- execution: [docs/EXECUTION_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/EXECUTION_LAYER_DESIGN.md)
- memory: [docs/MEMORY_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/MEMORY_LAYER_DESIGN.md)
- response: [docs/RESPONSE_LAYER_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/RESPONSE_LAYER_DESIGN.md)

## Local Development

- Python 3.11+
- Redis
- PostgreSQL
- optional QuickBooks app credentials for operational lookups

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
uvicorn src.main:app --reload
```

Open:

- app: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- endpoint: [http://127.0.0.1:8000/email-agent](http://127.0.0.1:8000/email-agent)

## Testing

```bash
python -m compileall src tests
pytest -q
```
