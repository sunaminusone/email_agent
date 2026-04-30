CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS service_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name TEXT NOT NULL UNIQUE,
    business_line TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    service_line TEXT,
    subcategory TEXT,
    page_title TEXT,
    document_summary TEXT,
    source_url TEXT,
    source_path TEXT,
    source_file TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_service_catalog_business_line
    ON service_catalog (business_line);

CREATE INDEX IF NOT EXISTS idx_service_catalog_page_title
    ON service_catalog (page_title);

CREATE INDEX IF NOT EXISTS idx_service_catalog_source_file
    ON service_catalog (source_file);
