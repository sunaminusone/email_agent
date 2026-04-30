from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from src.documents.retrieval.service_documents import (
    SERVICE_CATALOG_TABLE,
    SERVICE_DOCUMENTS_TABLE,
    build_connection_string,
)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - psycopg is required at runtime
    psycopg = None
    dict_row = None


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def document_catalog_inventory(
    *,
    infer_document_type,
    normalize_text,
    tokenize,
    normalize_business_line,
) -> list[dict[str, Any]]:
    """Read service-document metadata from Postgres.

    Returns one entry per active service_documents row, joined to its
    parent service_catalog row for canonical_name + business_line.
    Rows lacking storage_url are skipped — presigned URLs are minted
    later by the caller, only for top-ranked matches.
    """
    if psycopg is None:
        return []

    sql = f"""
        SELECT
            sd.file_name,
            sd.title,
            sd.document_type,
            sd.storage_url,
            sd.metadata,
            sc.canonical_name AS service_name,
            sc.business_line
        FROM {SERVICE_DOCUMENTS_TABLE} sd
        JOIN {SERVICE_CATALOG_TABLE} sc ON sd.service_id = sc.id
        WHERE sd.is_active = TRUE
    """

    try:
        with psycopg.connect(build_connection_string()) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
    except Exception as exc:
        logger.warning("document_catalog_inventory PG query failed: %s", exc)
        return []

    inventory: list[dict[str, Any]] = []
    for row in rows:
        storage_url = (row.get("storage_url") or "").strip()
        if not storage_url:
            continue

        file_name = (row.get("file_name") or "").strip()
        title = (row.get("title") or "").strip() or file_name
        document_type = (row.get("document_type") or "").strip() or infer_document_type(file_name)
        business_line = (row.get("business_line") or "").strip()
        service_name = (row.get("service_name") or "").strip()

        search_blob = " ".join(
            part for part in [file_name, title, service_name, business_line, document_type] if part
        )

        inventory.append(
            {
                "file_name": file_name,
                "source_path": storage_url,
                "storage_url": storage_url,
                "document_type": document_type,
                "business_line": business_line,
                "normalized_business_line": normalize_business_line(business_line),
                "title": title,
                "product_scope": "service_line",
                "product_name": service_name,
                "catalog_no": "",
                "normalized_name": normalize_text(search_blob),
                "tokens": tokenize(search_blob),
            }
        )
    return inventory
