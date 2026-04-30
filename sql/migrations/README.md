# sql/migrations

Numbered, idempotent SQL migration files applied in sequence on top of the
RDS-truth schema. Files in `sql/*.sql` (catalog_schema.sql etc.) are stale
historical DDL — do not use them as source of truth.

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
