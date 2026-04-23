# Email Agent

A modular biotech support agent for product, technical, document, and operational inquiries.

This project combines typed Python service layers, retrieval systems, LLM-based understanding, and persistent session memory to handle multi-turn support workflows. The current architecture is centered on a clear runtime sequence:

`memory recall -> ingestion -> object resolution -> routing -> executor -> response -> memory reflect`

For the full design set, start with [docs/ARCHITECTURE_READING_ORDER.md](/Users/promab/anaconda_projects/email_agent/docs/ARCHITECTURE_READING_ORDER.md).

## What This Project Does

The agent is designed for biotech customer-support and internal-assistant scenarios such as:

- understanding free-form customer questions
- resolving products, services, targets, and operational entities
- deciding whether to answer, clarify, or hand off
- retrieving grounded information from catalog data, technical RAG sources, local documents, and QuickBooks
- composing customer-facing replies from tool results instead of free-form hallucinated generation
- preserving session context across turns with typed memory

The main API entrypoint is [src/main.py](/Users/promab/anaconda_projects/email_agent/src/main.py), and the end-to-end runtime assembly lives in [src/app/service.py](/Users/promab/anaconda_projects/email_agent/src/app/service.py).

## Core Capabilities

- `Catalog lookup`: structured product retrieval, candidate ranking, and pricing-oriented support over PostgreSQL-backed catalog data
- `Technical RAG`: semantic retrieval over curated service-page corpora with scoped query rewriting, reranking, and response grounding
- `Document lookup`: local document inventory lookup and document-path surfacing
- `QuickBooks lookups`: customer, invoice, order, and shipping retrieval through the QuickBooks integration
- `Session memory`: Redis-backed recall and reflect flow for multi-turn continuity

## Runtime Flow

The current implementation in [src/app/service.py](/Users/promab/anaconda_projects/email_agent/src/app/service.py) follows this flow:

1. `recall()` loads prior typed memory and builds turn context.
2. `ingestion/` parses the incoming turn into an `IngestionBundle`.
3. `objects/` resolves products, services, targets, and ambiguous references into `ResolvedObjectState`.
4. `routing/` decides whether the agent should `execute`, `clarify`, `handoff`, or directly respond.
5. `executor/` selects tools from the registry, dispatches them, and merges grounded results.
6. `response/` composes the final answer, clarification, partial answer, or handoff message.
7. `reflect()` persists updated memory for the next turn.

## Architecture Principles

- Typed contracts connect every major layer.
- Tool execution is grounded in registered `ToolCapability` metadata.
- Response generation is constrained by retrieved facts and content blocks.
- Memory is explicit and typed, not implicit prompt stuffing.
- LLMs are used inside bounded stages rather than as the architecture itself.

## Project Layout

```text
src/
  agent/         # multi-group agent state and tool-call cache
  app/           # top-level runtime assembly
  catalog/       # structured catalog retrieval, ranking, selection
  common/        # shared models, messages, execution contracts
  config/        # runtime settings, LLM, embeddings, integration config
  documents/     # document inventory lookup over local files
  executor/      # tool selection, dispatch, merge, completeness logic
  ingestion/     # parser pipeline, deterministic signals, intent assembly
  integrations/  # external connectors such as QuickBooks
  memory/        # recall/reflect lifecycle and persistence adapters
  objects/       # entity extraction and resolution
  rag/           # vectorstore, scope-aware retrieval, reranking, ingestion
  response/      # content blocks, planning, rendering, rewrite
  routing/       # route decision and dialogue-act handling
  strategies/    # reusable heuristics
  tools/         # tool contracts, registry, mappers, implementations

docs/            # v3 architecture and subsystem design docs
frontend/        # browser UI for the prototype workspace
tests/           # integration and subsystem tests
data/            # local corpora, processed artifacts, vectorstore inputs
scripts/         # data import and evaluation scripts
```

## Important Data and Dependencies

This project currently depends on a few local and external systems:

- `OpenAI API`: used for chat completions and embeddings
- `Redis`: used for session memory persistence
- `PostgreSQL`: used for catalog and registry-backed lookups
- `Local document directories`: used by document retrieval
- `Local RAG corpora`: used by the technical retrieval pipeline
- `QuickBooks credentials`: optional, only needed for operational lookups

Some paths in the current codebase are still machine-specific and point into this repository's local `data/` directories. That means the app works best when run from this workspace as currently structured.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

The app reads configuration from `.env`.

Minimum commonly used variables:

```bash
OPENAI_API_KEY=...
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql://...
```

Optional QuickBooks variables:

```bash
QB_CLIENT_ID=...
QB_CLIENT_SECRET=...
QB_REDIRECT_URI=...
QB_ENVIRONMENT=sandbox
```

Relevant config lives in [src/config/settings.py](/Users/promab/anaconda_projects/email_agent/src/config/settings.py).

### 3. Start the app

```bash
uvicorn src.main:app --reload
```

Then open:

- App UI: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- LangServe endpoint: [http://127.0.0.1:8000/email-agent](http://127.0.0.1:8000/email-agent)
- Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## API Shape

The main request model is [AgentRequest](/Users/promab/anaconda_projects/email_agent/src/api_models.py:22).

At a high level, the API accepts:

- `thread_id`
- `user_query`
- `locale`
- `conversation_history`
- `attachments`

The response includes parsed signals, routing output, execution details, content blocks, and the final assistant message. The response model is [AgentPrototypeResponse](/Users/promab/anaconda_projects/email_agent/src/api_models.py:37).

## Development Notes

- The frontend is a prototype workspace, not just a bare API demo.
- The executor is demand-aware and capability-driven.
- The technical retrieval path currently focuses on curated service-page corpora in `data/processed/rag_ready_files`.
- The response layer is grounded through content blocks before optional rewrite.

## Tests

Run the main automated checks with:

```bash
python -m compileall src tests
pytest -q
```

I also verified a core subset locally while updating this README:

```bash
pytest -q tests/test_technical_inquiry.py tests/test_response_service.py tests/test_executor.py tests/test_routing_service.py
```

That subset currently passes.

## Design Docs

Start here:

- [docs/ARCHITECTURE_READING_ORDER.md](/Users/promab/anaconda_projects/email_agent/docs/ARCHITECTURE_READING_ORDER.md)

Primary v3 docs:

- [docs/AGENT_ARCHITECTURE_V3.md](/Users/promab/anaconda_projects/email_agent/docs/AGENT_ARCHITECTURE_V3.md)
- [docs/INGESTION_DESIGN_V3.md](/Users/promab/anaconda_projects/email_agent/docs/INGESTION_DESIGN_V3.md)
- [docs/MEMORY_DESIGN_V3.md](/Users/promab/anaconda_projects/email_agent/docs/MEMORY_DESIGN_V3.md)
- [docs/ROUTING_DESIGN_V3.md](/Users/promab/anaconda_projects/email_agent/docs/ROUTING_DESIGN_V3.md)
- [docs/EXECUTOR_DESIGN_V3.md](/Users/promab/anaconda_projects/email_agent/docs/EXECUTOR_DESIGN_V3.md)
- [docs/TOOL_CONTRACT_DESIGN_V3.md](/Users/promab/anaconda_projects/email_agent/docs/TOOL_CONTRACT_DESIGN_V3.md)

## Current Status

This repository is best understood as an actively evolving architecture prototype:

- the layering and typed contracts are already substantial
- the main agent path is runnable end to end
- the design docs are deeper than the README and remain the canonical architecture reference
- some infrastructure and file-path assumptions are still local-development oriented

## HubSpot Training Query Export

To export real inbound customer queries from HubSpot for agent training, set `HUBSPOT_ACCESS_TOKEN` in `.env`, then run:

`python scripts/export_hubspot_training_queries.py --out data/processed/hubspot_training_queries.jsonl`

Useful options:

- `--contact-email user@example.com` to export only specific contacts.
- `--emails-only` to export only CRM email engagements.
- `--conversations-only` to export only inbox conversation messages.

The exporter keeps inbound customer-side messages and writes one JSON object per line with `input_text`, contact metadata, timestamp, and recent context.
