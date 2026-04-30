BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS conversation_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_key TEXT NOT NULL UNIQUE,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversation_threads_updated_at
    ON conversation_threads (updated_at DESC);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES conversation_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    response_type TEXT,
    response_path TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread_id
    ON conversation_messages (thread_id, created_at);

CREATE TABLE IF NOT EXISTS conversation_message_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    document_label TEXT,
    document_url TEXT NOT NULL,
    file_name TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversation_message_documents_message_id
    ON conversation_message_documents (message_id);

COMMIT;
