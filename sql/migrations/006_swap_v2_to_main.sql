-- 006_swap_v2_to_main.sql
-- ----------------------------------------------------------------------------
-- Blue-green Phase 5: swap product_catalog_v2 into the canonical product_catalog
-- name. Final migration. RUN ONLY AFTER:
--
--   * 004 + 005 applied
--   * scripts/import_antibody_from_jsonl.py executed against v2 (antibody
--     rows from web JSONL fully populated)
--   * src/catalog/retrieval/* SQL switched to read from product_catalog_v2
--     and webui smoke tests passed for both antibody (price + immunogen +
--     dilutions visible) and CAR-T (existing flows unchanged)
--   * Manual sign-off: backup created, expected row count delta documented
--
-- This migration is destructive — DROPs the legacy product_catalog table.
-- Re-running is a no-op if v2 has already been renamed (the IF EXISTS
-- guards). Rollback within the same transaction works; once committed,
-- recovery requires the backup.
-- ----------------------------------------------------------------------------

BEGIN;

-- Take a snapshot first. PG's CREATE TABLE ... AS preserves the data but
-- not constraints / indexes — that's fine; the snapshot is for emergency
-- restoration only, not as a queryable replacement.
DROP TABLE IF EXISTS product_catalog_legacy_snapshot_20260504;
CREATE TABLE product_catalog_legacy_snapshot_20260504 AS
    TABLE product_catalog;

-- Drop the legacy table (and any indexes / triggers that reference it
-- directly). Foreign keys from other tables would block this — none
-- currently exist, but adding one in the future would have to be unwound
-- here first.
DROP TABLE IF EXISTS product_catalog;

-- Rename v2 into place. PG's RENAME is atomic at the catalog level;
-- existing prepared statements / pgbouncer pools may need a refresh,
-- but normal queries pick up the new relation immediately.
ALTER TABLE product_catalog_v2 RENAME TO product_catalog;

-- Rename the v2 indexes / constraints to match canonical names so
-- ALTER / DROP DDL written against the historical names keeps working.
ALTER INDEX IF EXISTS uq_pcv2_catalog_no                   RENAME TO product_catalog_catalog_no_key;
ALTER TABLE  product_catalog RENAME CONSTRAINT chk_pcv2_aliases_normalized_length TO chk_aliases_normalized_length;
ALTER INDEX IF EXISTS idx_pcv2_business_line               RENAME TO idx_pc_business_line;
ALTER INDEX IF EXISTS idx_pcv2_record_type                 RENAME TO idx_pc_record_type;
ALTER INDEX IF EXISTS idx_pcv2_host                        RENAME TO idx_pc_host;
ALTER INDEX IF EXISTS idx_pcv2_target_antigen              RENAME TO idx_pc_target_antigen;
ALTER INDEX IF EXISTS idx_pcv2_aliases_normalized_gin      RENAME TO idx_pc_aliases_normalized_gin;
ALTER INDEX IF EXISTS idx_pcv2_applications_gin            RENAME TO idx_pc_applications_gin;
ALTER INDEX IF EXISTS idx_pcv2_species_reactivity_gin      RENAME TO idx_pc_species_reactivity_gin;
ALTER INDEX IF EXISTS idx_pcv2_search_trgm                 RENAME TO idx_pc_search_trgm;

-- Rename the trigger function so its name reflects the new role.
ALTER FUNCTION refresh_product_catalog_v2_search() RENAME TO refresh_product_catalog_search;
DROP TRIGGER IF EXISTS trg_refresh_pcv2_search ON product_catalog;
CREATE TRIGGER trg_refresh_product_catalog_search
    BEFORE INSERT OR UPDATE ON product_catalog
    FOR EACH ROW EXECUTE FUNCTION refresh_product_catalog_search();

COMMIT;


-- ---------------------------------------------------------------------------
-- Post-swap verification (run manually):
--
--   SELECT business_line, count(*) FROM product_catalog
--    GROUP BY business_line ORDER BY count(*) DESC;
--
--   SELECT count(*) FROM product_catalog WHERE source_url IS NOT NULL;
--   -- expected: ≈ web antibody import row count (~4080)
--
--   SELECT count(*) FROM product_catalog WHERE business_line ~* 'antibody';
--   -- expected: ≈ web antibody import row count (~4080), all from web
--
-- The legacy snapshot product_catalog_legacy_snapshot_20260504 stays
-- around for two weeks then can be DROPped manually.
-- ---------------------------------------------------------------------------
