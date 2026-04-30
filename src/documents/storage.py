from __future__ import annotations

import os

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None


AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip()


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
