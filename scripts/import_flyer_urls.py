#!/usr/bin/env python3
"""Backfill {cart,lnp}_product_catalog.flyer_s3_url from S3.

For each business line (--line cart|lnp), walks the configured S3 prefix,
extracts the catalog_no from each PM-####.pdf filename, and UPDATEs the
matching child row (joined to product_catalog via product_id).

Idempotent: re-runs are no-ops once URLs are in sync. Run periodically to
catch newly uploaded flyers.

Usage
-----
    # dry-run CAR-T
    python scripts/import_flyer_urls.py --line cart

    # commit CAR-T
    python scripts/import_flyer_urls.py --line cart --apply

    # dry-run LNP
    python scripts/import_flyer_urls.py --line lnp

    # commit LNP
    python scripts/import_flyer_urls.py --line lnp --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import boto3
import psycopg
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]
AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip()

BUCKET = "promab-service-docs"

LINE_CONFIG: dict[str, dict] = {
    "cart": {
        "prefix": "catalog/car-t product catalog details flyers/",
        "sku_re": re.compile(r"(PM-CAR\d+)", re.IGNORECASE),
        "child_table": "cart_product_catalog",
    },
    "lnp": {
        "prefix": "catalog/mrna-lnp catalog details flyers/",
        "sku_re": re.compile(r"(PM-LNP-\d+)", re.IGNORECASE),
        "child_table": "lnp_product_catalog",
    },
}


def _list_flyer_keys(prefix: str) -> list[str]:
    client = boto3.client("s3", region_name=AWS_REGION)
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            if key.lower().endswith(".pdf"):
                keys.append(key)
    return keys


def _key_to_sku(key: str, sku_re: re.Pattern) -> str | None:
    filename = key.rsplit("/", 1)[-1]
    m = sku_re.search(filename)
    return m.group(1).upper() if m else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", required=True, choices=sorted(LINE_CONFIG))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cfg = LINE_CONFIG[args.line]
    prefix = cfg["prefix"]
    sku_re = cfg["sku_re"]
    child_table = cfg["child_table"]
    update_sql = f"""
        UPDATE {child_table} AS c
           SET flyer_s3_url = %(url)s
          FROM product_catalog AS p
         WHERE c.product_id = p.id
           AND p.catalog_no = %(sku)s
           AND (c.flyer_s3_url IS DISTINCT FROM %(url)s)
    """

    print(f"[info] line={args.line}  s3://{BUCKET}/{prefix}")
    keys = _list_flyer_keys(prefix)
    print(f"[info] found {len(keys)} PDF objects")

    sku_to_url: dict[str, str] = {}
    unparseable: list[str] = []
    for key in keys:
        sku = _key_to_sku(key, sku_re)
        if sku is None:
            unparseable.append(key)
            continue
        url = f"s3://{BUCKET}/{key}"
        prior = sku_to_url.get(sku)
        if prior is None or url < prior:
            sku_to_url[sku] = url

    if unparseable:
        print(f"[warn] {len(unparseable)} PDF(s) had no SKU regex match — skipped:")
        for k in unparseable[:10]:
            print(f"   {k}")
        if len(unparseable) > 10:
            print(f"   … and {len(unparseable) - 10} more")

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT 1 FROM information_schema.columns
             WHERE table_name = %s AND column_name = 'flyer_s3_url'
        """, (child_table,))
        if cur.fetchone() is None:
            print(f"[ERR] {child_table}.flyer_s3_url not found. Run the matching "
                  "migration first (009 for cart, 010 for lnp).", file=sys.stderr)
            sys.exit(1)

        cur.execute(f"""
            SELECT p.catalog_no
              FROM product_catalog p
              JOIN {child_table} c ON c.product_id = p.id
        """)
        known_skus = {r[0].upper() for r in cur.fetchall() if r[0]}
        print(f"[info] DB has {len(known_skus)} SKUs in {child_table}")

        s3_skus = set(sku_to_url)
        matched = sorted(s3_skus & known_skus)
        s3_only = sorted(s3_skus - known_skus)
        db_only = sorted(known_skus - s3_skus)

        print(f"[info] S3 SKUs: {len(s3_skus)}; matched: {len(matched)}; "
              f"S3-only (no DB row): {len(s3_only)}; DB-only (no flyer): {len(db_only)}")
        if s3_only:
            print(f"[warn] {len(s3_only)} flyer(s) reference SKU not in DB:")
            for sku in s3_only[:20]:
                print(f"   {sku}  ({sku_to_url[sku]})")
            if len(s3_only) > 20:
                print(f"   … and {len(s3_only) - 20} more")

        updated = 0
        for sku in matched:
            cur.execute(update_sql, {"url": sku_to_url[sku], "sku": sku})
            updated += cur.rowcount
        print(f"[info] rows updated (changed value): {updated}")

        cur.execute(f"""
            SELECT COUNT(*) FILTER (WHERE c.flyer_s3_url IS NOT NULL),
                   COUNT(*)
              FROM {child_table} c
        """)
        with_url, total = cur.fetchone()
        print(f"[verify] {child_table}: {with_url}/{total} rows have flyer_s3_url")

        if not args.apply:
            conn.rollback()
            print("\n[DRY RUN] rolled back. Re-run with --apply to commit.")
        else:
            conn.commit()
            print("\n[COMMITTED]")


if __name__ == "__main__":
    main()
