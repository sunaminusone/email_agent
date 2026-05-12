-- 009_cart_flyer_s3_url.sql
-- ----------------------------------------------------------------------------
-- Add flyer_s3_url to cart_product_catalog so the frontend can surface a link
-- to each CAR-T SKU's product flyer PDF stored in S3 (bucket
-- promab-service-docs, prefix "catalog/car-t product catalog details flyers/").
-- The column holds an s3:// URI; the API generates a presigned https URL on
-- demand via src/documents/storage.py:generate_presigned_document_url.
--
-- Antibody / mRNA-LNP flyer columns are deferred until those S3 prefixes are
-- populated. (mRNA-LNP already exposes a separate web datasheet via
-- lnp_product_catalog.data_sheet_url, which is unrelated to this column.)
-- ----------------------------------------------------------------------------

BEGIN;

ALTER TABLE cart_product_catalog
    ADD COLUMN IF NOT EXISTS flyer_s3_url TEXT;

COMMENT ON COLUMN cart_product_catalog.flyer_s3_url IS
    's3:// URI of the CAR-T product flyer PDF (bucket promab-service-docs). Backend turns this into a presigned https URL at request time.';

COMMIT;
