-- 006_swap_v2_to_main.sql
-- ----------------------------------------------------------------------------
-- Blue-green Phase 5: swap product_catalog_v2 + antibody_product_catalog_v2
-- into the canonical names. Final migration. RUN ONLY AFTER:
--
--   * 004 + 005 applied
--   * scripts/import_antibody_from_jsonl.py executed against v2 (antibody
--     parent + child rows from web JSONL fully populated)
--   * src/catalog/retrieval/* SQL switched to read from product_catalog_v2
--     (with LEFT JOIN antibody_product_catalog_v2 where antibody detail
--     is needed) and webui smoke tests passed for both antibody (price +
--     immunogen + dilutions visible) and CAR-T (existing flows unchanged)
--   * Manual sign-off: backup created, expected row count delta documented
--
-- This migration is destructive — DROPs the legacy product_catalog table.
-- Re-running is a no-op if v2 has already been renamed (the IF EXISTS
-- guards). Rollback within the same transaction works; once committed,
-- recovery requires the snapshot table.
-- ----------------------------------------------------------------------------

BEGIN;

-- ---------------------------------------------------------------------------
-- Snapshot legacy data first.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS product_catalog_legacy_snapshot_20260504;
CREATE TABLE product_catalog_legacy_snapshot_20260504 AS
    TABLE product_catalog;

-- ---------------------------------------------------------------------------
-- Drop legacy parent. No FK references currently exist on the legacy
-- product_catalog (verified 2026-05-04); adding one in the future would
-- have to be unwound here first.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS product_catalog;

-- ---------------------------------------------------------------------------
-- Rename v2 parent into place. PG's RENAME is atomic at the catalog level;
-- existing prepared statements / pgbouncer pools may need a refresh.
-- ---------------------------------------------------------------------------
ALTER TABLE product_catalog_v2 RENAME TO product_catalog;

-- Rename child (1:1 antibody facet).
ALTER TABLE antibody_product_catalog_v2 RENAME TO antibody_product_catalog;

-- ---------------------------------------------------------------------------
-- Rename v2 indexes / constraints / FK to canonical names so any DDL
-- written against the historical names keeps working.
-- ---------------------------------------------------------------------------

-- Parent: constraints
ALTER INDEX IF EXISTS uq_pcv2_catalog_no                   RENAME TO product_catalog_catalog_no_key;
ALTER TABLE  product_catalog RENAME CONSTRAINT chk_pcv2_aliases_normalized_length TO chk_aliases_normalized_length;

-- Parent: indexes
ALTER INDEX IF EXISTS idx_pcv2_business_line               RENAME TO idx_pc_business_line;
ALTER INDEX IF EXISTS idx_pcv2_record_type                 RENAME TO idx_pc_record_type;
ALTER INDEX IF EXISTS idx_pcv2_target_antigen              RENAME TO idx_pc_target_antigen;
ALTER INDEX IF EXISTS idx_pcv2_aliases_normalized_gin      RENAME TO idx_pc_aliases_normalized_gin;
ALTER INDEX IF EXISTS idx_pcv2_applications_gin            RENAME TO idx_pc_applications_gin;
ALTER INDEX IF EXISTS idx_pcv2_species_reactivity_gin      RENAME TO idx_pc_species_reactivity_gin;
ALTER INDEX IF EXISTS idx_pcv2_search_trgm                 RENAME TO idx_pc_search_trgm;

-- Child: indexes
ALTER INDEX IF EXISTS idx_apcv2_host                       RENAME TO idx_apc_host;
ALTER INDEX IF EXISTS idx_apcv2_isotype                    RENAME TO idx_apc_isotype;
ALTER INDEX IF EXISTS idx_apcv2_gene_id                    RENAME TO idx_apc_gene_id;

-- ---------------------------------------------------------------------------
-- Rename trigger function + trigger so their names reflect the new role.
-- ---------------------------------------------------------------------------
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
--   -- antibody parent rows should equal antibody child rows
--   SELECT
--     (SELECT count(*) FROM product_catalog WHERE business_line ~* 'antibody') AS parent_antibody,
--     (SELECT count(*) FROM antibody_product_catalog) AS child_total;
--
--   -- spot-check JOIN integrity
--   SELECT p.catalog_no, p.name, a.host, a.isotype, a.elisa_dilution
--   FROM product_catalog p
--   LEFT JOIN antibody_product_catalog a ON a.product_id = p.id
--   WHERE p.business_line ~* 'antibody'
--   LIMIT 5;
--
-- The legacy snapshot product_catalog_legacy_snapshot_20260504 stays
-- around for two weeks then can be DROPped manually.
-- ---------------------------------------------------------------------------
