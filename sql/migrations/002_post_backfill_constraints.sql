-- Migration 002 (post-backfill): now that aliases_normalized is populated,
-- enforce the length-equals invariant. This catches the most common writer
-- footgun (updating aliases without updating aliases_normalized) at zero
-- runtime cost.
--
-- Cannot be merged into 001 because at that point aliases_normalized is
-- still '[]' for all rows; the CHECK would fail immediately.
--
-- Run AFTER scripts/backfill_aliases_normalized.py completes.
--
-- Idempotent: safe to re-run.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_aliases_normalized_length'
    ) THEN
        ALTER TABLE product_catalog
        ADD CONSTRAINT chk_aliases_normalized_length
        CHECK (jsonb_array_length(aliases) = jsonb_array_length(aliases_normalized));
    END IF;
END $$;

COMMIT;
