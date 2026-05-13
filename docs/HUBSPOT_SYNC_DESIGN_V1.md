# HubSpot Sync Design v1

## Purpose

This document defines the current and planned design for syncing HubSpot
email activity into the agent's internal historical-thread store.

The immediate goal is narrow:

1. incrementally fetch recent HubSpot form submissions
2. normalize each submission plus its reply chain into the existing
   `historical_threads` and `historical_thread_messages` tables
3. make those threads available to historical retrieval and later draft jobs

This is not a customer-facing automation system. The sync layer only
refreshes internal evidence.

## Current v1 Scope

The current implementation supports:

- incremental form-submission scan based on `submitted_at`
- one normalized historical thread per HubSpot form submission
- reply-chain sync using the existing `thread_messages` export shape
- normalization into the existing historical-thread schema
- PostgreSQL write-through on `--apply`
- local sync cursor persistence in a state JSON file

Current entrypoints:

- sync service: [src/data_sources/hubspot/sync.py](/Users/promab/anaconda_projects/email_agent/src/data_sources/hubspot/sync.py)
- CLI wrapper: [scripts/sync_hubspot_incremental.py](/Users/promab/anaconda_projects/email_agent/scripts/sync_hubspot_incremental.py)

## Why This Lives In `data_sources/hubspot`

HubSpot is not just an offline export tool and not just an agent tool.
Long-term it is a reusable data source that may support:

- historical email retrieval
- real-time new-email intake
- attachment lookup
- training export
- future thread-level context enrichment for draft generation

So the correct boundary is:

- `src/data_sources/hubspot/` owns HubSpot fetch + normalization logic
- scheduler / webhook owns triggering
- agent runtime consumes the synced data later

## Current Flow

```text
external scheduler / manual run
  -> scripts/sync_hubspot_incremental.py
  -> HubSpotIncrementalSync.sync_to_postgres()
  -> fetch recent HubSpot form submissions
  -> load each submission's modeled reply chain
  -> normalize into historical_threads / historical_thread_messages
  -> optionally write to PostgreSQL
  -> persist sync cursor to state file
```

## Current Persistence Model

The sync writes into the existing historical-thread storage rather than
creating a second email-history schema.

Tables used:

- `historical_threads`
- `historical_thread_messages`

Why:

- the retrieval pipeline already knows how to use this shape
- the CSR draft layer already expects this source of historical evidence
- a single normalized thread store is easier to reason about than
  parallel HubSpot-specific tables for the same agent use case

Synthetic thread ids are currently used:

- `hubspot-form-{submission_id}`

This is acceptable for v1 because the immediate requirement is internal
retrieval and continuity, not exact external mirror fidelity.

## Sync State

The sync cursor is stored locally in:

- `data/processed/hubspot_incremental_sync_state.json`

Current state fields include:

- `last_sync_at`
- `last_run_at`
- `last_submissions_synced`
- `last_threads_prepared`
- `last_messages_prepared`

This is sufficient for v1 local operation. It is not the final production
state strategy.

## Triggering Strategy

### Current recommendation

Run the sync externally every 5 hours.

Do not embed a long-lived `while true` loop inside the application
runtime. The sync logic should stay one-shot and re-entrant; scheduling
should stay outside the code path.

Recommended trigger options:

- `cron`
- `launchd`
- system scheduler / job runner

### Why not an in-process loop

- couples the API process to scheduling concerns
- makes restart behavior and failure recovery harder
- complicates observability
- becomes brittle once draft jobs, delivery jobs, and webhook triggers exist

## Planned Evolution

The intended long-term flow is:

```text
HubSpot webhook and/or scheduler
  -> HubSpot sync job
  -> internal thread store update
  -> draft task enqueue
  -> draft worker
  -> CSR delivery email / internal notification
```

The recommended rollout sequence is:

1. stabilize incremental sync
2. trigger a draft job after new thread/message intake
3. email the draft bundle to CSR internal recipients
4. add webhook-based fast-path triggering
5. keep periodic sync as a backstop for missed webhook events

## Separation Of Responsibilities

These boundaries should stay clean:

- `data_sources/hubspot`
  fetches HubSpot data and normalizes it
- sync store layer
  writes normalized rows into PostgreSQL
- draft job
  builds draft + references from newly synced evidence
- delivery layer
  sends internal CSR-facing email notifications
- scheduler / webhook
  triggers jobs but does not own business logic

The sync step should not directly send customer mail and should not
become the place where full draft generation logic accumulates.

## Known v1 Constraints

- `src/data_sources/hubspot/sync.py` is a bit too large and currently mixes
  orchestration, normalization, persistence, and state handling
- local JSON state is fine for one environment but not ideal for
  multi-instance deployment
- the sync currently follows the form-submission model, so non-form inbound
  email that never anchors to a submission is outside v1 scope
- synthetic thread ids are internal convenience ids, not canonical CRM ids

## Refactor Direction

When this area grows, split `sync.py` into:

- `sync.py` for orchestration only
- `fetchers.py` for HubSpot read operations
- `normalizers.py` for HubSpot -> historical-thread conversion
- `store.py` for PostgreSQL write logic
- `state.py` for cursor persistence

This should be treated as a cleanup refactor, not a behavior change.

## Operational Guidance

Typical usage:

Dry run:

```bash
python scripts/sync_hubspot_incremental.py --submission-limit 20
```

Write to PostgreSQL:

```bash
python scripts/sync_hubspot_incremental.py --apply --submission-limit 20
```

For now, this is the preferred operational model: one-shot sync command,
scheduled externally, with the code remaining stateless between runs
except for the explicit sync cursor file.
