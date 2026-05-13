-- 007_cti_split_cart_lnp.sql
-- ----------------------------------------------------------------------------
-- CTI split phase 1: promote CAR-T/CAR-NK and mRNA-LNP business lines into
-- their own 1:1 child tables (mirrors the antibody_product_catalog pattern).
-- Also adds a plaintext `description` column to antibody_product_catalog;
-- the existing description_html stays put until 008 (drop after consumer
-- switch). All four parent columns (formulation/shipping/storage/description)
-- and the antibody column rename (shipping_information → shipping, drop
-- description_html) are deferred to 008.
--
-- Apply order
--   007 (this file): CREATE child tables + indexes + ADD antibody.description
--   scripts/migrate_cti_split.py --apply: data move + HTML→text strip
--   (consumer switch in src/catalog/retrieval/* and src/objects/*)
--   008: DROP redundant parent columns; RENAME antibody.shipping_information →
--        shipping; DROP antibody.description_html
-- ----------------------------------------------------------------------------

BEGIN;

-- ===========================================================================
-- cart_product_catalog — CTI child for CAR-T/CAR-NK
-- ===========================================================================
CREATE TABLE IF NOT EXISTS cart_product_catalog (
    product_id           UUID PRIMARY KEY
        REFERENCES product_catalog(id) ON DELETE CASCADE,

    -- CAR-T-specific (sourced from product_catalog.attributes JSONB pre-007)
    construct            TEXT,
    costimulatory_domain TEXT,
    group_name           TEXT,
    group_type           TEXT,
    group_subtype        TEXT,
    group_summary        TEXT,
    cell_number          TEXT,
    marker               TEXT,
    unit                 TEXT,

    -- Common provenance (sourced from product_catalog.{formulation,shipping,
    -- storage,description} pre-007; those parent columns are dropped in 008)
    formulation          TEXT,
    shipping             TEXT,
    storage              TEXT,
    description          TEXT,

    raw_metafields       JSONB
);

COMMENT ON TABLE cart_product_catalog IS
    'CTI child of product_catalog: CAR-T/CAR-NK first-class fields. 1:1 with parent via product_id PK + FK CASCADE.';
COMMENT ON COLUMN cart_product_catalog.construct IS
    'CAR construct designation (e.g. CD19 scFv-TM-CD28-CD3z).';
COMMENT ON COLUMN cart_product_catalog.costimulatory_domain IS
    'Costimulatory signaling domain (CD28 / 4-1BB / etc.).';
COMMENT ON COLUMN cart_product_catalog.group_name IS
    'Web product group name (CAR-T Cells / Empty Vector Control / etc.).';
COMMENT ON COLUMN cart_product_catalog.cell_number IS
    'Cell count per vial as text (e.g. "1×10^6").';

CREATE INDEX IF NOT EXISTS idx_cart_construct
    ON cart_product_catalog (construct) WHERE construct IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cart_group_name
    ON cart_product_catalog (group_name) WHERE group_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cart_group_type
    ON cart_product_catalog (group_type) WHERE group_type IS NOT NULL;


-- ===========================================================================
-- lnp_product_catalog — CTI child for mRNA-LNP
-- ===========================================================================
CREATE TABLE IF NOT EXISTS lnp_product_catalog (
    product_id           UUID PRIMARY KEY
        REFERENCES product_catalog(id) ON DELETE CASCADE,

    -- LNP-specific (sourced from product_catalog.attributes JSONB pre-007;
    -- web metafield names normalized: applicationHanding → application_handling,
    -- dataSheet → data_sheet_url, cellTypeTested → cell_type_tested)
    type                 TEXT,                                           -- encoded protein type: Protein / CAR / Antibody / Control
    application          TEXT,
    application_handling TEXT,
    cell_type_tested     TEXT,
    data_sheet_url       TEXT,

    -- Common provenance
    formulation          TEXT,
    shipping             TEXT,
    storage              TEXT,
    description          TEXT,

    raw_metafields       JSONB
);

COMMENT ON TABLE lnp_product_catalog IS
    'CTI child of product_catalog: mRNA-LNP first-class fields. 1:1 with parent via product_id PK + FK CASCADE.';
COMMENT ON COLUMN lnp_product_catalog.type IS
    'mRNA-encoded payload type (Protein / CAR / Antibody / Control). Web metafield "type".';
COMMENT ON COLUMN lnp_product_catalog.application_handling IS
    'Free-form handling instructions for the encoded payload application (typo-fixed from web metafield "applicationHanding").';
COMMENT ON COLUMN lnp_product_catalog.data_sheet_url IS
    'PDF datasheet URL on promab.com (web metafield "dataSheet").';

CREATE INDEX IF NOT EXISTS idx_lnp_type
    ON lnp_product_catalog (type) WHERE type IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lnp_application
    ON lnp_product_catalog (application) WHERE application IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lnp_cell_type_tested
    ON lnp_product_catalog (cell_type_tested) WHERE cell_type_tested IS NOT NULL;


-- ===========================================================================
-- antibody_product_catalog: add plaintext description (from description_html)
-- ===========================================================================
ALTER TABLE antibody_product_catalog
    ADD COLUMN IF NOT EXISTS description TEXT;

COMMENT ON COLUMN antibody_product_catalog.description IS
    'Plaintext rendering of description_html (HTML stripped + entities unescaped). Filled by scripts/migrate_cti_split.py.';


-- ===========================================================================
-- product_catalog: GIN on attributes for future JSONB filtering
-- ===========================================================================
CREATE INDEX IF NOT EXISTS idx_pc_attributes_gin
    ON product_catalog USING gin (attributes);


COMMIT;
