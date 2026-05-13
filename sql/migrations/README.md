# sql/migrations

Numbered, idempotent SQL migration files applied in sequence on top of the
RDS-truth schema.

## What lives where

- `sql/*.sql` — **standalone schemas** for first-time table creation
  (`service_registry_schema.sql`, `service_documents_schema.sql`, etc.).
  Idempotent (`CREATE TABLE IF NOT EXISTS`), apply once when bootstrapping
  a fresh database. Older files like `catalog_schema.sql` are stale historical
  DDL — the live `product_catalog` shape is in RDS, not in any sql/ file.
- `sql/migrations/NNN_*.sql` — **incremental migrations** that mutate an
  existing table (add columns / indexes / constraints, rename, backfill).
  Apply in numbered order, every file wrapped in `BEGIN; … COMMIT;` and
  guarded by `IF NOT EXISTS` / `IF EXISTS` so re-runs are no-ops.

## Apply order

```
001_pre_backfill_business_line_key_aliases_normalized.sql
scripts/backfill_aliases_normalized.py --apply
002_post_backfill_constraints.sql
```

## Conventions

- Filename `NNN_short_description.sql`, three-digit zero-padded sequence.
- Every file wrapped in `BEGIN; … COMMIT;`.
- Every DDL guarded by `IF NOT EXISTS` / `IF EXISTS` so re-runs are no-ops.
- Migrations that need Python (e.g. normalize logic that does not round-trip
  through SQL) are split into pre/post pairs around a script.

## Apply checklist

- `\d product_catalog` before/after to confirm column + index landed
- Run dry-run (`--apply` omitted) for any Python step first
- Run a smoke query against the new index: `EXPLAIN (ANALYZE) SELECT ...`
