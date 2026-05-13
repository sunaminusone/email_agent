CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS service_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id UUID NOT NULL REFERENCES service_catalog(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    storage_url TEXT NOT NULL,
    file_name TEXT,
    mime_type TEXT,
    file_size BIGINT,
    version TEXT,
    extracted_text TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_service_documents_service_id
    ON service_documents (service_id);

CREATE INDEX IF NOT EXISTS idx_service_documents_type
    ON service_documents (document_type);

CREATE INDEX IF NOT EXISTS idx_service_documents_storage_url
    ON service_documents (storage_url);

ALTER TABLE service_catalog
ADD COLUMN IF NOT EXISTS primary_document_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_service_catalog_primary_document'
    ) THEN
        ALTER TABLE service_catalog
        ADD CONSTRAINT fk_service_catalog_primary_document
        FOREIGN KEY (primary_document_id)
        REFERENCES service_documents(id)
        ON DELETE SET NULL;
    END IF;
END $$;
