-- 010_lnp_flyer_s3_url.sql
-- ----------------------------------------------------------------------------
-- Mirror of 009 for the mRNA-LNP business line. Adds flyer_s3_url to
-- lnp_product_catalog so the frontend can surface a link to each LNP SKU's
-- internal product flyer PDF stored in S3 (bucket promab-service-docs,
-- prefix "catalog/mrna-lnp catalog details flyers/").
--
-- This is distinct from the existing data_sheet_url column on the same table:
--   * data_sheet_url -- external promab.com web datasheet (web metafield "dataSheet")
--   * flyer_s3_url   -- internal CSR catalog flyer in our S3 bucket
-- ----------------------------------------------------------------------------

BEGIN;

ALTER TABLE lnp_product_catalog
    ADD COLUMN IF NOT EXISTS flyer_s3_url TEXT;

COMMENT ON COLUMN lnp_product_catalog.flyer_s3_url IS
    's3:// URI of the mRNA-LNP product flyer PDF (bucket promab-service-docs). Backend turns this into a presigned https URL at request time. Distinct from data_sheet_url which is the external web datasheet on promab.com.';

COMMIT;
