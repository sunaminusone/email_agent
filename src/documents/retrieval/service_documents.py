from __future__ import annotations

import os
import time
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None

from src.documents.storage import generate_presigned_document_url


SERVICE_CATALOG_TABLE = os.getenv("OBJECTS_SERVICE_REGISTRY_TABLE", "service_catalog").strip() or "service_catalog"
SERVICE_DOCUMENTS_TABLE = os.getenv("SERVICE_DOCUMENTS_TABLE", "service_documents").strip() or "service_documents"


def build_connection_string() -> str:
    from src.common.pg_runtime import with_runtime_timeouts

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return with_runtime_timeouts(database_url)

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    dbname = os.getenv("PGDATABASE", "promab")
    auth = user if not password else f"{user}:{password}"
    return with_runtime_timeouts(f"postgresql://{auth}@{host}:{port}/{dbname}")


def get_primary_service_document(service_name: str) -> dict[str, Any] | None:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed.")

    sql = f"""
        SELECT
            sc.id AS service_id,
            sc.canonical_name,
            sd.id AS document_id,
            sd.document_type,
            sd.title,
            sd.storage_url,
            sd.file_name,
            sd.mime_type,
            sd.file_size,
            sd.version,
            sd.metadata
        FROM {SERVICE_CATALOG_TABLE} sc
        JOIN {SERVICE_DOCUMENTS_TABLE} sd
            ON sc.primary_document_id = sd.id
        WHERE sc.canonical_name = %s
    """
    with psycopg.connect(build_connection_string()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (service_name,))
            row = cur.fetchone()
    return dict(row) if row else None


_LINK_CACHE_SAFETY_MARGIN_S = 300
_link_cache: dict[str, tuple[dict[str, Any], float]] = {}


def get_primary_service_document_link(service_name: str, *, expires_in: int = 3600) -> dict[str, Any] | None:
    cached = _link_cache.get(service_name)
    if cached is not None and cached[1] > time.time():
        return cached[0]

    record = get_primary_service_document(service_name)
    if not record:
        return None
    presigned_url = generate_presigned_document_url(record["storage_url"], expires_in=expires_in)
    link = {
        **record,
        "presigned_url": presigned_url,
        "expires_in": expires_in,
    }
    expires_at = time.time() + max(1, expires_in - _LINK_CACHE_SAFETY_MARGIN_S)
    _link_cache[service_name] = (link, expires_at)
    return link
