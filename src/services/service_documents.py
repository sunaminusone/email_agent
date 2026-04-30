"""Service document lookup + S3 presigned URL minting.

Runtime requirements:
  - PostgreSQL: DATABASE_URL or PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE
    pointing at a database that has the service_catalog + service_documents
    schemas applied (see sql/service_registry_schema.sql and
    sql/service_documents_schema.sql).
  - AWS S3 access: boto3 picks up credentials from the environment in this
    order — AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars, ~/.aws/credentials,
    or the IAM role attached to the host. Without any of those,
    generate_presigned_document_url raises NoCredentialsError on first call,
    not at import time. Configure AWS_REGION (default us-east-1) for the
    bucket region.
"""
from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None

from src.config.settings import BASE_DIR


load_dotenv(BASE_DIR / ".env")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip()
SERVICE_CATALOG_TABLE = os.getenv("OBJECTS_SERVICE_REGISTRY_TABLE", "service_catalog").strip() or "service_catalog"
SERVICE_DOCUMENTS_TABLE = os.getenv("SERVICE_DOCUMENTS_TABLE", "service_documents").strip() or "service_documents"


def build_connection_string() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    dbname = os.getenv("PGDATABASE", "promab")
    auth = user if not password else f"{user}:{password}"
    return f"postgresql://{auth}@{host}:{port}/{dbname}"


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


def parse_s3_url(storage_url: str) -> tuple[str, str]:
    normalized = str(storage_url or "").strip()
    prefix = "s3://"
    if not normalized.startswith(prefix):
        raise ValueError(f"Unsupported S3 URL format: {storage_url}")
    remainder = normalized[len(prefix):]
    if "/" not in remainder:
        raise ValueError(f"S3 URL is missing object key: {storage_url}")
    bucket, key = remainder.split("/", 1)
    return bucket, key


def generate_presigned_document_url(storage_url: str, *, expires_in: int = 3600) -> str:
    if boto3 is None:
        raise RuntimeError("boto3 is not installed.")
    bucket, key = parse_s3_url(storage_url)
    client = boto3.client("s3", region_name=AWS_REGION)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


# TTL cache for presigned-link lookups: each entry is (link_dict, expires_at_epoch).
# We expire 5 min before the URL itself does, so an in-flight CSR draft never
# hands out a link about to die. Process-local — survives across turns within
# one Python process, dropped on restart.
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
