-- 008_drop_parent_redundant.sql
-- ----------------------------------------------------------------------------
-- CTI split phase 2 (cleanup, paired with 007 + scripts/migrate_cti_split.py).
-- Now that consumer code reads formulation/shipping/storage/description from
-- the three CTI children via COALESCE, the parent's copies are redundant.
-- Also collapse the antibody column-name drift:
--   shipping_information → shipping  (matches cart_/lnp_product_catalog)
--   description_html DROP             (007 already populated description plaintext)
--
-- IMPORTANT: consumer code in src/catalog/retrieval/shared.py and
-- src/objects/registries/product_registry.py must be updated to read
-- a.shipping (instead of a.shipping_information) BEFORE running this.
-- ----------------------------------------------------------------------------

BEGIN;

-- antibody column drift cleanup
ALTER TABLE antibody_product_catalog
    RENAME COLUMN shipping_information TO shipping;

ALTER TABLE antibody_product_catalog
    DROP COLUMN IF EXISTS description_html;

-- parent now-redundant common provenance columns
ALTER TABLE product_catalog DROP COLUMN IF EXISTS formulation;
ALTER TABLE product_catalog DROP COLUMN IF EXISTS shipping;
ALTER TABLE product_catalog DROP COLUMN IF EXISTS storage;
ALTER TABLE product_catalog DROP COLUMN IF EXISTS description;

COMMIT;
