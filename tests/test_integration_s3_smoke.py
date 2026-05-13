"""S3 credential + presigned-URL smoke test.

Two tiers, both gated by ``--integration``:

1. ``test_aws_credentials_active`` only needs the AWS credential chain
   (``~/.aws/credentials`` or ``AWS_*`` env). Catches credential rot /
   region mismatch independently of the catalog database.
2. ``test_service_document_presigned_url_round_trip`` pulls one real
   ``s3://`` URL out of ``service_documents``, mints a presigned URL
   via the production helper, and ``HEAD``s it — exercising both the
   PG schema and the bucket policy + object existence end-to-end.

Run with ``pytest tests/test_integration_s3_smoke.py --integration``.
"""
from __future__ import annotations

import boto3
import psycopg
import pytest
import requests

from src.catalog.retrieval.shared import build_connection_string
from src.documents.storage import generate_presigned_document_url

pytestmark = pytest.mark.integration


def test_aws_credentials_active() -> None:
    sts = boto3.client("sts")
    identity = sts.get_caller_identity()
    assert identity.get("Account"), "STS get_caller_identity returned no account"
    assert identity.get("Arn", "").startswith("arn:aws:"), identity


def test_service_document_presigned_url_round_trip() -> None:
    with psycopg.connect(build_connection_string()) as conn:
        cur = conn.execute(
            "SELECT storage_url FROM service_documents "
            "WHERE storage_url LIKE 's3://%' "
            "ORDER BY id LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        pytest.skip("service_documents has no s3:// rows yet")

    storage_url = row[0]
    presigned = generate_presigned_document_url(storage_url, expires_in=60)
    assert presigned.startswith("https://"), presigned

    # The URL is signed for GET (generate_presigned_document_url uses
    # ClientMethod="get_object"); V2 SigV4 is method-bound, so HEAD with
    # the same URL returns 403. Stream a GET and close immediately —
    # avoids downloading the full PDF just for the round-trip check.
    response = requests.get(presigned, timeout=10, allow_redirects=True, stream=True)
    try:
        assert response.status_code == 200, (
            f"GET {storage_url} -> {response.status_code}; "
            "check bucket policy / object existence / region"
        )
    finally:
        response.close()
