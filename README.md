# Email Agent

A modular biotech customer-support agent built with FastAPI and LangServe.

The system is designed around a clear runtime pipeline:

`parser -> conversation -> context -> decision -> orchestration -> tools/integrations -> response -> responders`

It supports:
- product and pricing lookup
- documentation lookup over local PDF metadata
- technical retrieval over RAG
- QuickBooks customer / invoice / order / shipping lookup
- multi-turn conversation continuity with Redis-backed session memory

## Project Layout

```text
src/
  orchestration/   # shared lifecycle: parse -> context -> route -> plan -> execute -> respond
  parser/          # current-turn understanding only
  conversation/    # turn resolution, reference resolution, payload merge, AgentContext assembly
  decision/        # route decision and response decision
  response/        # response content building and response chain assembly
  catalog/         # product search pipeline: retrieval -> ranking -> selection -> service
  documents/       # document search pipeline: retrieval -> ranking -> selection -> service
  rag/             # semantic technical retrieval
  integrations/    # low-level external system connectors (QuickBooks)
  context/         # RuntimeContext assembly and prompt formatting
  memory/          # session persistence (Redis)
  tools/           # LLM-callable atomic actions
  responders/      # final natural-language rendering
  schemas/         # shared typed models
  strategies/      # reusable rule-based heuristics
  agents/          # domain role implementations
```

## Architecture Conventions

These boundaries are intentional and should stay stable as the project grows.

- `agents/` contains domain role implementations; `orchestration/` contains the shared lifecycle.
- `integrations/` contains low-level clients/connectors; `tools/` contains LLM-callable actions built on top of them.
- `parser/` only understands the current user turn and returns `ParsedResult`.
- `conversation/` merges `ParsedResult` with session state and produces `AgentContext`.
- `decision/` decides routing and response focus; it should not own storage or external API code.
- `response/` turns response strategy plus execution results into grounded content and final response payloads.
- `catalog/`, `documents/`, `rag/`, and `integrations/` are capability/data layers, not orchestration layers.

## Runtime Flow

1. `parser/` converts the current user message into `ParsedResult`.
2. `conversation/` applies turn resolution, reference resolution, session payload reuse, and query resolution to build `AgentContext`.
3. `context/` assembles `RuntimeContext` from memory, documents, and retrieval sources.
4. `decision/` selects route and response focus.
5. `orchestration/` plans and executes tools.
6. `response/` builds content blocks, tries typed renderers, and falls back to LLM generation when needed.
7. `responders/` provide the rendering layer for supported typed topics.

## Key Features

### Multi-turn state

- Redis-backed session memory keyed by `thread_id`
- persisted route state and session payload
- turn resolution for `new_request`, `follow_up`, and `clarification_answer`
- reference resolution for phrases like `this one`, `the other one`, and `same product`

### Data capabilities

- `catalog/`: structured product search pipeline with retrieval, ranking, and selection over PostgreSQL
- `documents/`: document search pipeline over `document_catalog.csv` and local PDFs
- `rag/`: semantic retrieval for technical questions
- `integrations/quickbooks/`: OAuth, token management, query repository, and result matching

### Service-Page RAG

- Service-page `rag_ready` authoring and ingestion conventions are documented in [docs/SERVICE_PAGE_RAG_STANDARD.md](/Users/promab/anaconda_projects/email_agent/docs/SERVICE_PAGE_RAG_STANDARD.md)

### Response stack

- `decision/response_resolution/`: topic, focus, style, and content-policy selection
- `response/content/`: atomic content blocks, clarification/handoff, and legacy fallback resolution
- `responders/renderers/`: topic-based deterministic renderers
- `responders/legacy/`: reduced legacy fallback responders kept only for summary-style fallback

## Local Development

- Python 3.11+
- Redis
- PostgreSQL
- Optional: QuickBooks app credentials for operational lookups

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment

Typical `.env` values:

```env
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
MEMORY_TTL_SECONDS=7200
MEMORY_MAX_TURNS=10
MEMORY_KEY_PREFIX=email_agent:session

QB_CLIENT_ID=
QB_CLIENT_SECRET=
QB_REDIRECT_URI=
QB_ENVIRONMENT=sandbox
QB_SCOPE=com.intuit.quickbooks.accounting
```

## Run

Start the app with Uvicorn:

```bash
uvicorn src.main:app --reload
```

Then open:

- app: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- LangServe endpoint: [http://127.0.0.1:8000/email-agent](http://127.0.0.1:8000/email-agent)

## QuickBooks Endpoints

- status: [http://127.0.0.1:8000/qb/status](http://127.0.0.1:8000/qb/status)
- connect: [http://127.0.0.1:8000/qb/connect](http://127.0.0.1:8000/qb/connect)
- callback: `/qb/callback`

## Documents

Local PDFs are served from:

- [/Users/promab/anaconda_projects/email_agent/data/raw/pdf](/Users/promab/anaconda_projects/email_agent/data/raw/pdf)

Document metadata is read from:

- [/Users/promab/anaconda_projects/email_agent/data/processed/document_catalog.csv](/Users/promab/anaconda_projects/email_agent/data/processed/document_catalog.csv)

## Testing

Compile check:

```bash
python -m compileall src tests
```

Current regression suite:

```bash
pytest -q tests/test_turn_resolution_regression.py tests/test_response_generation_regression.py
```

## Current Notes

- The old `src/services/` compatibility layer has been retired.
- Image upload/vision analysis has been intentionally removed for now and can be reintroduced later as a dedicated module.
- The old `chains/` and `prompts/` directories have been retired; routing prompt logic now lives under `src/decision/`.
- Legacy responders have been reduced to a minimal fallback path while topic renderers handle the main response flow.
