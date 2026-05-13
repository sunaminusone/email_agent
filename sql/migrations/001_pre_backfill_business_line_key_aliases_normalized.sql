-- Migration 001 (pre-backfill): add business_line_key + aliases_normalized columns,
-- backfill business_line_key inline (cheap), leave aliases_normalized empty
-- (filled by scripts/backfill_aliases_normalized.py because SQL cannot
-- replicate normalize_object_alias business logic 1:1).
--
-- Idempotent: safe to re-run.
--
-- Apply order:
--   1. psql -f 001_pre_backfill_business_line_key_aliases_normalized.sql
--   2. python scripts/backfill_aliases_normalized.py
--   3. psql -f 002_post_backfill_constraints.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- business_line_key (S2): canonical snake_case enum, aligned with service_catalog
-- ---------------------------------------------------------------------------

ALTER TABLE product_catalog
    ADD COLUMN IF NOT EXISTS business_line_key TEXT;

UPDATE product_catalog
SET business_line_key = CASE business_line
    WHEN 'Antibody'     THEN 'antibody'
    WHEN 'CAR-T/CAR-NK' THEN 'car_t_car_nk'
    WHEN 'mRNA-LNP'     THEN 'mrna_lnp'
    ELSE business_line_key
END
WHERE business_line_key IS NULL
   OR business_line_key NOT IN ('antibody', 'car_t_car_nk', 'mrna_lnp');

-- Hard fail if any row still has NULL — surfaces unknown business_line values
-- so we add them explicitly rather than silently let NOT NULL drop the row.
DO $$
DECLARE
    null_count INTEGER;
    unknown_lines TEXT;
BEGIN
    SELECT COUNT(*) INTO null_count
    FROM product_catalog WHERE business_line_key IS NULL;

    IF null_count > 0 THEN
        SELECT string_agg(DISTINCT business_line, ', ')
        INTO unknown_lines
        FROM product_catalog WHERE business_line_key IS NULL;
        RAISE EXCEPTION
            'business_line_key NULL for % rows; unknown business_line values: %',
            null_count, unknown_lines;
    END IF;
END $$;

ALTER TABLE product_catalog
    ALTER COLUMN business_line_key SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pc_business_line_key
    ON product_catalog (business_line_key);

-- ---------------------------------------------------------------------------
-- target_antigen index (high-frequency CAR-T / Antibody filter)
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_pc_target_antigen
    ON product_catalog (target_antigen)
    WHERE target_antigen IS NOT NULL;

-- ---------------------------------------------------------------------------
-- aliases_normalized (S1 i'): JSONB array of normalized strings, populated
-- by the Python backfill. Default '[]' so existing rows stay valid.
-- ---------------------------------------------------------------------------

ALTER TABLE product_catalog
    ADD COLUMN IF NOT EXISTS aliases_normalized JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Default jsonb_ops GIN (NOT jsonb_path_ops) — required for ? / ?| / ?&
-- operators that direct_alias_lookup will use for exact normalized membership.
CREATE INDEX IF NOT EXISTS idx_pc_aliases_normalized_gin
    ON product_catalog USING gin (aliases_normalized);

COMMIT;
