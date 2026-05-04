#!/usr/bin/env python3
"""Scrape product prices from promab.com and backfill product_catalog.price.

Background
----------
The catalog DB was loaded from Excel exports without prices; ProMab's public
storefront (Next.js + Shopify backend) has them embedded in the
``__NEXT_DATA__`` JSON of every product detail page under
``props.pageProps.props.product.variants[*].price``.

This script is a one-time backfill, idempotent (re-runs overwrite). When
prices drift on the website, re-run with ``--update-db``.

Strategy
--------
1. Enumerate product URLs from the 17 sub-sitemaps under
   ``/sitemap/sitemap-product/{N}.xml``.
2. For each URL: fetch HTML, regex-extract ``<script id="__NEXT_DATA__">``,
   parse JSON, walk to product variants.
3. Map Shopify variant SKU (e.g. ``10005-100ul`` / ``PM-CAR1008-1ml``) back
   to ``catalog_no`` by matching against the same shape patterns the
   ingestion-time deterministic regex uses (P + 5 digits / 5-digit + letter /
   PM-...). Only update DB rows where the catalog_no exists.
4. When a product has multiple size variants, pick the cheapest (entry
   price). DB schema has a single ``price`` column so multi-size products
   collapse to "starting from" — CSR can probe larger sizes on the website.

Usage
-----
    # dry-run on first sitemap only, dump CSV for review
    python scripts/scrape_promab_prices.py --sitemaps 1 --csv /tmp/prices.csv

    # full run, write to DB
    python scripts/scrape_promab_prices.py --update-db
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import psycopg
except ImportError:
    psycopg = None

from src.catalog.retrieval.shared import build_connection_string


SITEMAP_INDEX_URL = "https://www.promab.com/sitemap/sitemap-product/{n}.xml"
SITEMAP_COUNT = 17
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
    re.DOTALL,
)
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")

# Shape-locked catalog_no patterns (mirrors src/ingestion/deterministic_signals.py
# 2026-05-02 RDS audit: 99.9% of active rows match one of these).
CATALOG_SHAPES = (
    re.compile(r"^P\d{5}$"),
    re.compile(r"^\d{5}[A-Z]*$"),
    re.compile(r"^PM-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$"),
)
# Variant SKUs end in ``-{size}`` where size is a number + unit
# (100ul / 100μl / 1mg / 100ug / 1ml / 50µg etc.). Strip that suffix to
# recover the catalog_no.
SIZE_SUFFIX_RE = re.compile(
    r"-\d+(?:\.\d+)?\s*[uµμmnpkl]?[lLgG]$",
    re.IGNORECASE,
)


@dataclass
class VariantRecord:
    catalog_no: str
    sku: str
    size: str
    price: Decimal
    source_url: str


@dataclass
class ProductRecord:
    """Full product capture from a single page — every field the front-end
    surfaces is preserved as-is so downstream transforms can pivot to any
    format (CAR-T xlsx columns, antibody catalog enrichment, etc.) without
    re-scraping. Title, bodyHtml description, all metafields (which carry
    the Product Overview rows like Aliases / Host / Isotype / Immunogen /
    Formulation / Storage and the Product Applications dilutions like
    westernBlotting / elisa), all variants (size + price), and image URLs
    all land here verbatim."""

    source_url: str
    title: str
    handle: str
    vendor: str
    tags: list[str]
    body_html: str
    metafields: dict[str, object]
    variants: list[dict[str, object]]
    images: list[str]
    catalog_no: str  # resolved canonical (prefers metafields.sku, else variant prefix)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def enumerate_product_urls(sitemap_indices: Iterable[int]) -> list[str]:
    urls: list[str] = []
    for idx in sitemap_indices:
        sitemap_url = SITEMAP_INDEX_URL.format(n=idx)
        try:
            xml = _fetch(sitemap_url)
        except urllib.error.URLError as exc:
            print(f"[warn] sitemap {idx} fetch failed: {exc}", file=sys.stderr)
            continue
        found = LOC_RE.findall(xml)
        urls.extend(found)
        print(f"[info] sitemap {idx}: {len(found)} URLs")
    return urls


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def _resolve_catalog_no(product: dict, variants: list[dict]) -> str:
    """Return the canonical catalog_no in upper-case.

    Priority:
    1. ``metafields.sku`` — most reliable for CAR-T / mRNA where Shopify
       variant SKUs are null but the catalog # lives in metafields
       (e.g. PM-CAR1100).
    2. Strip the size suffix from the first non-empty variant SKU
       (antibody pattern, e.g. "10005-100μl" → "10005").
    Returns "" if neither produces a usable value.
    """
    mf = product.get("metafields") or {}
    mf_sku = (mf.get("sku") or "").strip()
    if mf_sku:
        return mf_sku.upper()
    for v in variants:
        sku = (v.get("sku") or "").strip()
        if not sku:
            continue
        size_match = SIZE_SUFFIX_RE.search(sku)
        prefix = sku[: size_match.start()] if size_match else sku
        return prefix.upper()
    return ""


def extract_product_record(html: str, source_url: str) -> ProductRecord | None:
    """Parse a product detail page's __NEXT_DATA__ JSON and return the full
    captured record. Returns None when the page has no embedded product
    object (404-shaped pages, or template that doesn't expose product).
    """
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    product = (
        data.get("props", {})
        .get("pageProps", {})
        .get("props", {})
        .get("product")
    )
    if not product:
        return None
    variants = product.get("variants") or []
    images_raw = product.get("images") or []
    image_urls: list[str] = []
    for img in images_raw:
        if isinstance(img, dict):
            url = img.get("src") or img.get("url") or img.get("originalSrc") or ""
            if url:
                image_urls.append(str(url))
        elif isinstance(img, str):
            image_urls.append(img)
    return ProductRecord(
        source_url=source_url,
        title=str(product.get("title") or ""),
        handle=str(product.get("handle") or ""),
        vendor=str(product.get("vendor") or ""),
        tags=list(product.get("tags") or []),
        body_html=str(product.get("bodyHtml") or ""),
        metafields=dict(product.get("metafields") or {}),
        variants=[dict(v) for v in variants if isinstance(v, dict)],
        images=image_urls,
        catalog_no=_resolve_catalog_no(product, variants),
    )


def variants_from_product(record: ProductRecord) -> list[VariantRecord]:
    """Project the rich ProductRecord onto the CSV/DB-write VariantRecord
    schema: one row per priced variant. Skips variants with zero/missing
    price."""
    out: list[VariantRecord] = []
    for v in record.variants:
        v_sku = (v.get("sku") or "").strip()
        title = str(v.get("title") or "")
        # CAR-T variants have null SKU; size lives in `title`.
        if v_sku:
            size_match = SIZE_SUFFIX_RE.search(v_sku)
            size = size_match.group(0).lstrip("-") if size_match else title
        else:
            size = title
        price_raw = v.get("price")
        if price_raw in (None, "", "0", "0.0", "0.00"):
            continue
        try:
            price = Decimal(str(price_raw))
        except (InvalidOperation, TypeError):
            continue
        out.append(
            VariantRecord(
                catalog_no=record.catalog_no,
                sku=v_sku or record.catalog_no,
                size=size,
                price=price,
                source_url=record.source_url,
            )
        )
    return out


def select_entry_variant(records: list[VariantRecord]) -> VariantRecord:
    """When a product offers multiple size variants, pick the cheapest as
    the "starting from" entry price. The DB has a single price column so
    multi-size products collapse to one row; the smallest size price is
    what matters most for CSR triage."""
    return min(records, key=lambda r: r.price)


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def apply_to_db(records: dict[str, VariantRecord]) -> dict[str, int]:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; cannot --update-db")
    if not records:
        return {"updated": 0, "no_match": 0}

    updated = 0
    no_match = 0
    with psycopg.connect(build_connection_string()) as conn:
        with conn.cursor() as cur:
            for catalog_no, rec in records.items():
                cur.execute(
                    "UPDATE product_catalog SET price = %s, "
                    "currency = COALESCE(currency, 'USD') "
                    "WHERE catalog_no = %s",
                    (rec.price, catalog_no),
                )
                if cur.rowcount > 0:
                    updated += 1
                else:
                    no_match += 1
        conn.commit()
    return {"updated": updated, "no_match": no_match}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sitemaps",
        type=int,
        nargs="+",
        default=list(range(1, SITEMAP_COUNT + 1)),
        help=f"Sub-sitemap indices to process (default 1..{SITEMAP_COUNT}).",
    )
    p.add_argument("--limit", type=int, default=0, help="Cap URLs scraped (0 = no cap).")
    p.add_argument("--rate", type=float, default=0.4, help="Seconds between page requests.")
    p.add_argument(
        "--jsonl",
        default="",
        help="Path to dump full product records (one JSON per product per "
        "line; preserves title / metafields / bodyHtml / all variants / "
        "images verbatim). Recommended primary output — CSV is a derived view.",
    )
    p.add_argument("--csv", default="", help="Optional flat per-variant view (catalog_no/sku/size/price/url).")
    p.add_argument("--update-db", action="store_true", help="Write prices to product_catalog (default dry-run).")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    print(f"[info] sitemaps={args.sitemaps}  limit={args.limit}  update_db={args.update_db}")

    urls = enumerate_product_urls(args.sitemaps)
    if args.limit > 0:
        urls = urls[: args.limit]
    print(f"[info] total URLs to scrape: {len(urls)}")

    by_catalog: dict[str, VariantRecord] = {}
    all_variants: list[VariantRecord] = []
    products: list[ProductRecord] = []
    skipped_no_product = 0
    skipped_no_priced_variants = 0
    fetch_errors = 0

    jsonl_fh = open(args.jsonl, "w") if args.jsonl else None

    try:
        for i, url in enumerate(urls, 1):
            try:
                html = _fetch(url)
            except (urllib.error.URLError, TimeoutError) as exc:
                fetch_errors += 1
                if fetch_errors <= 5:
                    print(f"[warn] fetch failed {url}: {exc}", file=sys.stderr)
                time.sleep(args.rate)
                continue
            record = extract_product_record(html, url)
            if record is None:
                skipped_no_product += 1
                time.sleep(args.rate)
                continue
            products.append(record)
            if jsonl_fh is not None:
                jsonl_fh.write(
                    json.dumps(
                        {
                            "source_url": record.source_url,
                            "catalog_no": record.catalog_no,
                            "title": record.title,
                            "handle": record.handle,
                            "vendor": record.vendor,
                            "tags": record.tags,
                            "body_html": record.body_html,
                            "metafields": record.metafields,
                            "variants": record.variants,
                            "images": record.images,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            variants = variants_from_product(record)
            if not variants:
                skipped_no_priced_variants += 1
            else:
                all_variants.extend(variants)
                entry = select_entry_variant(variants)
                existing = by_catalog.get(entry.catalog_no)
                if existing is None or entry.price < existing.price:
                    by_catalog[entry.catalog_no] = entry
            if i % 100 == 0:
                print(
                    f"[progress] {i}/{len(urls)}  products={len(products)}  "
                    f"unique_catalog={len(by_catalog)}  variants={len(all_variants)}  "
                    f"fetch_err={fetch_errors}"
                )
            time.sleep(args.rate)
    finally:
        if jsonl_fh is not None:
            jsonl_fh.close()

    print()
    print(f"[summary] urls scraped         : {len(urls)}")
    print(f"[summary] fetch errors         : {fetch_errors}")
    print(f"[summary] no product in JSON   : {skipped_no_product}")
    print(f"[summary] product but no price : {skipped_no_priced_variants}")
    print(f"[summary] products captured    : {len(products)}")
    print(f"[summary] total variants       : {len(all_variants)}")
    print(f"[summary] unique catalog_no    : {len(by_catalog)}")

    if args.jsonl:
        print(f"[info] wrote JSONL: {args.jsonl}")
    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["catalog_no", "title", "sku", "size", "price", "source_url"])
            # Build catalog_no → title lookup so the per-variant CSV carries
            # the page heading without a join step downstream.
            title_by_catalog = {p.catalog_no: p.title for p in products}
            for rec in all_variants:
                w.writerow([
                    rec.catalog_no,
                    title_by_catalog.get(rec.catalog_no, ""),
                    rec.sku,
                    rec.size,
                    str(rec.price),
                    rec.source_url,
                ])
        print(f"[info] wrote CSV: {args.csv}")

    if args.update_db:
        if psycopg is None:
            print("[error] psycopg not installed", file=sys.stderr)
            return 2
        stats = apply_to_db(by_catalog)
        print(f"[db] updated={stats['updated']}  no_match (catalog not in DB)={stats['no_match']}")
    else:
        print("[info] dry-run (no DB write). Re-run with --update-db to apply.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
