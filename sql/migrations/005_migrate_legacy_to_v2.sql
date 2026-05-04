-- 005_migrate_legacy_to_v2.sql
-- ----------------------------------------------------------------------------
-- Blue-green Phase 2: copy non-antibody rows from product_catalog into
-- product_catalog_v2.
--
-- Antibody rows are deliberately NOT migrated — they're being replaced
-- wholesale by web-scraped data via scripts/import_antibody_from_jsonl.py.
-- This is the boss-mandated direction (web-as-source-of-truth for
-- antibody, 2026-05-04). See memory project_antibody_web_enrichment_plan.md.
--
-- CAR-T / mRNA-LNP / Custom Service / other business lines carry forward
-- as-is. Their antibody-shaped first-class columns (host / isotype /
-- clone / immunogen / etc.) start NULL — these business lines simply
-- don't have those concepts. The pre-existing attributes JSONB carries
-- their actual data (construct / group_* / costimulatory_domain / etc.)
-- which is preserved verbatim by the SELECT below.
--
-- Idempotent: ON CONFLICT (catalog_no) DO NOTHING — re-running this
-- migration after partial failure won't duplicate rows. Combined with
-- the catalog_no UNIQUE constraint that means it's safe to rerun.
-- ----------------------------------------------------------------------------

INSERT INTO product_catalog_v2 (
    -- Identity
    id,
    catalog_no,
    -- Classification
    business_line,
    record_type,
    -- Naming
    name,
    target_antigen,
    -- Pricing
    price,
    currency,
    lead_time_text,
    -- Collections
    aliases,
    aliases_normalized,
    applications,
    species_reactivity,
    -- Free-form bag (carries CAR-T construct / group_* / costim_domain etc.)
    attributes,
    -- Audit
    is_active,
    created_at,
    updated_at
    -- Antibody-specific columns (host / isotype / immunogen / etc.)
    -- intentionally OMITTED so they default to NULL — the legacy
    -- product_catalog never carried these as first-class columns; if
    -- any CAR-T / mRNA row happens to have e.g. "host" in attributes
    -- JSONB it stays in attributes (no auto-promotion).
)
SELECT
    pc.id,
    pc.catalog_no,
    pc.business_line,
    pc.record_type,
    pc.name,
    pc.target_antigen,
    pc.price,
    coalesce(pc.currency, 'USD'),
    pc.lead_time_text,
    coalesce(pc.aliases, '[]'::jsonb),
    coalesce(pc.aliases_normalized, '[]'::jsonb),
    coalesce(pc.applications, '[]'::jsonb),
    coalesce(pc.species_reactivity, '[]'::jsonb),
    -- Old product_type and format are dropped. If a downstream consumer
    -- still wants them, they survive in attributes via the import
    -- script's raw_metadata; but the dedicated columns are gone.
    -- product_type / format were never antibody-relevant either.
    coalesce(pc.attributes, '{}'::jsonb)
        -- Carry forward the legacy product_type / format values into
        -- attributes for any downstream code that still reads them. This
        -- is a defensive carry — it can be dropped in a follow-up once
        -- code paths are confirmed to no longer reference them.
        || coalesce(jsonb_strip_nulls(jsonb_build_object(
            'legacy_product_type', pc.product_type,
            'legacy_format',       pc.format
        )), '{}'::jsonb),
    coalesce(pc.is_active, TRUE),
    coalesce(pc.created_at, CURRENT_TIMESTAMP),
    coalesce(pc.updated_at, CURRENT_TIMESTAMP)
FROM product_catalog pc
WHERE pc.business_line !~* 'antibody'      -- antibody rows excluded — replaced by web import
ON CONFLICT (catalog_no) DO NOTHING;


-- ---------------------------------------------------------------------------
-- Sanity check: emit counts so the migration runner / human can compare.
-- These RAISE NOTICEs go to PG logs; harmless if no one reads them.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    legacy_total           INTEGER;
    legacy_antibody        INTEGER;
    legacy_non_antibody    INTEGER;
    v2_total               INTEGER;
BEGIN
    SELECT count(*) INTO legacy_total FROM product_catalog;
    SELECT count(*) INTO legacy_antibody FROM product_catalog WHERE business_line ~* 'antibody';
    SELECT count(*) INTO legacy_non_antibody FROM product_catalog WHERE business_line !~* 'antibody';
    SELECT count(*) INTO v2_total FROM product_catalog_v2;

    RAISE NOTICE 'product_catalog rows total          : %', legacy_total;
    RAISE NOTICE 'product_catalog rows antibody       : % (NOT migrated; web import handles these)', legacy_antibody;
    RAISE NOTICE 'product_catalog rows non-antibody   : % (migrated → v2)', legacy_non_antibody;
    RAISE NOTICE 'product_catalog_v2 rows total       : %', v2_total;
    RAISE NOTICE '';
    RAISE NOTICE 'expected: v2_total = legacy_non_antibody + (web antibody import to be run after this migration)';
END $$;
