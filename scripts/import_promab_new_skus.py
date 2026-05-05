#!/usr/bin/env python3
"""Scrape promab.com sitemap and import any new CAR-T / mRNA-LNP SKUs.

The CAR-T phase 1 + mRNA-LNP phase 1 backfills (memory:
project_cart_web_enrichment_phase1, project_lnp_web_enrichment_phase1)
identified web-only SKUs that did not exist in DB:

  * 13 CAR-T:  PM-CAR1096..1101, 1103..1109 (-copy slugs mostly)
  * 1  LNP:    PM-LNP-0035

This script is the import side: walk the public sitemap, fetch every
CAR-T and mRNA-LNP product page, parse __NEXT_DATA__.props.pageProps.props.product
metafields, then INSERT (parent + child) for any SKU not already in
product_catalog. SKUs already present are left alone — re-runs are no-ops.

Usage
-----
    # dry-run: scrape, report which SKUs would be inserted, no DB write
    python scripts/import_promab_new_skus.py

    # commit
    python scripts/import_promab_new_skus.py --apply
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
import psycopg
from psycopg.types.json import Jsonb

from src.objects.normalizers import clean_text as _clean_text
from src.objects.normalizers import normalize_object_alias as _normalize_object_alias

load_dotenv(ROOT / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]


SITEMAP_INDEX = "https://www.promab.com/sitemap.xml"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', re.DOTALL
)
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")

CART_URL_PAT = re.compile(r"/products/car-t-car-nk/")
LNP_URL_PAT = re.compile(r"/products/products/mrna-lipid-nanoparticles/")


def _fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[warn] fetch failed {url}: {exc}", file=sys.stderr)
        return None


def _enumerate_sitemap_urls() -> list[str]:
    """Collect every product URL from the 17 sub-sitemaps."""
    index = _fetch(SITEMAP_INDEX) or ""
    sub_sitemaps = LOC_RE.findall(index)
    out: list[str] = []
    for sm in sub_sitemaps:
        if "sitemap-product" not in sm:
            continue
        body = _fetch(sm) or ""
        out.extend(LOC_RE.findall(body))
    return out


def _walk_facebook_description(obj: Any) -> str | None:
    """Locate seo.facebookMeta.description in __NEXT_DATA__."""
    if isinstance(obj, dict):
        seo = obj.get("seo")
        if isinstance(seo, dict):
            fb = seo.get("facebookMeta")
            if isinstance(fb, dict):
                d = fb.get("description")
                if isinstance(d, str) and d.strip():
                    return d.strip()
        for v in obj.values():
            r = _walk_facebook_description(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _walk_facebook_description(v)
            if r:
                return r
    return None


def _walk_product(obj: Any) -> dict | None:
    """Locate the dict that has 'metafields' AND 'sku' inside metafields.
    The CAR-T page has it at props.pageProps.props.product; LNP at the same
    relative spot."""
    if isinstance(obj, dict):
        if "metafields" in obj and isinstance(obj.get("metafields"), dict):
            mf = obj["metafields"]
            if mf.get("sku"):
                return obj
        for v in obj.values():
            r = _walk_product(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _walk_product(v)
            if r is not None:
                return r
    return None


def _strip(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _clean_mojibake(s: str | None) -> str | None:
    if s is None:
        return None
    return s.replace("Â°", "°")


def _norm_alias(alias: str) -> str:
    primary = _normalize_object_alias(alias)
    if primary:
        return primary
    fallback = _clean_text(alias).lower()
    return fallback or "__empty__"


def _cheapest_variant(variants: list[dict]) -> tuple[Decimal | None, str | None, list[dict]]:
    """Return (price, size_label, all_priced_variants) for the cheapest variant."""
    priced: list[tuple[Decimal, dict]] = []
    for v in variants or []:
        try:
            p = Decimal(str(v.get("price")))
            if p > 0:
                priced.append((p, v))
        except (InvalidOperation, TypeError):
            continue
    if not priced:
        return None, None, []
    priced.sort(key=lambda t: t[0])
    cheapest = priced[0][1]
    all_priced = [{"size": v.get("title") or "", "price": str(p)} for p, v in priced]
    return Decimal(str(cheapest.get("price"))), _strip(cheapest.get("title")), all_priced


def _parse_page(url: str) -> tuple[str, dict | None, str | None]:
    """Return (url, parsed_record, error). parsed_record carries everything we
    need for both parent and child rows; error is non-None on failure."""
    html = _fetch(url)
    if not html:
        return url, None, "fetch_failed"
    m = NEXT_DATA_RE.search(html)
    if not m:
        return url, None, "no_next_data"
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        return url, None, f"json_decode: {exc}"

    product = _walk_product(data)
    if product is None:
        return url, None, "no_product_with_sku"

    mf = product["metafields"]
    sku = _strip(mf.get("sku"))
    if not sku:
        return url, None, "no_sku"
    sku = sku.upper()

    title = _strip(product.get("title"))
    if not title:
        return url, None, "no_title"

    price, size, all_priced = _cheapest_variant(product.get("variants") or [])
    price_variants = all_priced if len(all_priced) > 1 else None

    images = product.get("images") or []
    raw_image = images[0] if images else None
    if isinstance(raw_image, dict):
        image_url = raw_image.get("src") or raw_image.get("url")
    elif isinstance(raw_image, str):
        image_url = raw_image
    else:
        image_url = None
    tags = product.get("tags") or []
    description = _clean_mojibake(_walk_facebook_description(data))

    # Business-line routing by metafield content: the /products/car-t-car-nk/
    # subtree carries CAR-T cells, NK cells, target cell lines, T-cell beads,
    # and reagent kits — but only true CAR-T cells expose `carConstruct` in
    # metafields. Use that as the discriminator. mRNA-LNP is detected by URL
    # since its metafields don't carry a single-key tell. Anything else in
    # the car-t-car-nk subtree is ancillary and goes to "Other Products"
    # (parent only, no child row, full metafields preserved in attributes).
    has_construct = bool(_strip(mf.get("carConstruct")))
    if has_construct:
        business_line = "CAR-T/CAR-NK"
    elif LNP_URL_PAT.search(url):
        business_line = "mRNA-LNP"
    elif CART_URL_PAT.search(url):
        business_line = "Other Products"
    else:
        return url, None, "not_cart_or_lnp"

    return url, {
        "sku": sku,
        "title": title,
        "handle": _strip(product.get("handle")),
        "business_line": business_line,
        "price": price,
        "size": size,
        "price_variants": price_variants,
        "image_url": image_url,
        "tags": list(tags),
        "description": description,
        "metafields": mf,
        "url": url,
    }, None


def _build_parent_row(rec: dict) -> dict:
    """Map parsed record → product_catalog row dict."""
    mf = rec["metafields"]
    aliases: list[str] = []
    bl = rec["business_line"]
    if bl == "CAR-T/CAR-NK":
        target_antigen = _strip(mf.get("targetAntigen"))
        record_type = "cell_product"
        attributes: dict = {}
    elif bl == "mRNA-LNP":
        target_antigen = None
        record_type = _strip(mf.get("type"))
        attributes = {}
    else:
        # "Other Products" — no child row, so stash the full metafields dict
        # in attributes JSONB for future promotion / inspection.
        target_antigen = None
        record_type = _strip(mf.get("type"))
        attributes = dict(mf)
    return {
        "catalog_no":         rec["sku"],
        "business_line":      bl,
        "record_type":        record_type,
        "name":               rec["title"],
        "target_antigen":     target_antigen,
        "price":              rec["price"],
        "price_variants":     Jsonb(rec["price_variants"]) if rec["price_variants"] else None,
        "currency":           "USD",
        "size":               rec["size"],
        "lead_time_text":     None,
        "aliases":            Jsonb(aliases),
        "aliases_normalized": Jsonb([_norm_alias(a) for a in aliases]),
        "applications":       Jsonb([]),
        "species_reactivity": Jsonb([]),
        "web_tags":           Jsonb(list(rec["tags"])),
        "attributes":         Jsonb(attributes),
        "image_url":          rec["image_url"],
        "source_url":         rec["url"],
        "web_handle":         rec["handle"],
        "is_active":          True,
    }


def _build_cart_child(rec: dict) -> dict:
    mf = rec["metafields"]
    return {
        "construct":            _strip(mf.get("carConstruct")),
        "costimulatory_domain": _strip(mf.get("costimulatoryDomain")),
        "group_name":           _strip(mf.get("groupName")),
        "group_type":           _strip(mf.get("groupType")),
        "group_subtype":        _strip(mf.get("groupSubtype")),
        "group_summary":        _strip(mf.get("groupSummary")),
        "cell_number":          _strip(mf.get("cellNumber")),
        "marker":               _strip(mf.get("marker")),
        "unit":                 _strip(mf.get("unit")),
        "formulation":          _clean_mojibake(_strip(mf.get("formulation"))),
        "shipping":             _clean_mojibake(_strip(mf.get("shippingInformation"))),
        "storage":              _clean_mojibake(_strip(mf.get("storage"))),
        "description":          rec["description"],
        "raw_metafields":       Jsonb(dict(mf)),
    }


def _build_lnp_child(rec: dict) -> dict:
    mf = rec["metafields"]
    return {
        "type":                 _strip(mf.get("type")),
        "application":          _strip(mf.get("application")),
        "application_handling": _strip(mf.get("applicationHanding")),
        "cell_type_tested":     _strip(mf.get("cellTypeTested")),
        "data_sheet_url":       _strip(mf.get("dataSheet")),
        "formulation":          _clean_mojibake(_strip(mf.get("composition"))),
        "shipping":             _clean_mojibake(_strip(mf.get("shippingInformation"))),
        "storage":              _clean_mojibake(_strip(mf.get("storage"))),
        "description":          rec["description"],
        "raw_metafields":       Jsonb(dict(mf)),
    }


PARENT_INSERT = """
    INSERT INTO product_catalog (
        catalog_no, business_line, record_type, name, target_antigen,
        price, price_variants, currency, size, lead_time_text,
        aliases, aliases_normalized, applications, species_reactivity, web_tags,
        attributes, image_url, source_url, web_handle, is_active, last_synced_at
    ) VALUES (
        %(catalog_no)s, %(business_line)s, %(record_type)s, %(name)s, %(target_antigen)s,
        %(price)s, %(price_variants)s, %(currency)s, %(size)s, %(lead_time_text)s,
        %(aliases)s, %(aliases_normalized)s, %(applications)s, %(species_reactivity)s, %(web_tags)s,
        %(attributes)s, %(image_url)s, %(source_url)s, %(web_handle)s, %(is_active)s, CURRENT_TIMESTAMP
    )
    RETURNING id;
"""

CART_CHILD_INSERT = """
    INSERT INTO cart_product_catalog (
        product_id, construct, costimulatory_domain, group_name, group_type,
        group_subtype, group_summary, cell_number, marker, unit,
        formulation, shipping, storage, description, raw_metafields
    ) VALUES (
        %(product_id)s, %(construct)s, %(costimulatory_domain)s, %(group_name)s, %(group_type)s,
        %(group_subtype)s, %(group_summary)s, %(cell_number)s, %(marker)s, %(unit)s,
        %(formulation)s, %(shipping)s, %(storage)s, %(description)s, %(raw_metafields)s
    );
"""

LNP_CHILD_INSERT = """
    INSERT INTO lnp_product_catalog (
        product_id, type, application, application_handling,
        cell_type_tested, data_sheet_url,
        formulation, shipping, storage, description, raw_metafields
    ) VALUES (
        %(product_id)s, %(type)s, %(application)s, %(application_handling)s,
        %(cell_type_tested)s, %(data_sheet_url)s,
        %(formulation)s, %(shipping)s, %(storage)s, %(description)s, %(raw_metafields)s
    );
"""


CACHE_PATH = Path("/tmp/promab_cart_lnp_parsed.jsonl")


def main() -> None:
    apply = "--apply" in sys.argv
    use_cache = "--use-cache" in sys.argv and CACHE_PATH.exists()

    if use_cache:
        print(f"[info] loading cached scrape from {CACHE_PATH}")
        parsed: list[dict] = []
        with CACHE_PATH.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    parsed.append(json.loads(line))
        print(f"[info] cache: {len(parsed)} records")
    else:
        print("[info] enumerating sitemap …")
        all_urls = _enumerate_sitemap_urls()
        cart_urls = [u for u in all_urls if CART_URL_PAT.search(u)]
        lnp_urls = [u for u in all_urls if LNP_URL_PAT.search(u)]
        print(f"[info] CAR-T URLs: {len(cart_urls)}, mRNA-LNP URLs: {len(lnp_urls)}")

        targets = cart_urls + lnp_urls
        parsed = []
        errors: list[tuple[str, str]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            for url, rec, err in ex.map(_parse_page, targets):
                if err:
                    errors.append((url, err))
                elif rec:
                    parsed.append(rec)
        print(f"[info] parsed {len(parsed)} pages with SKU; {len(errors)} errors")
        if errors:
            for u, e in errors[:5]:
                print(f"   {e}: {u}")

        # Cache to JSONL so a PG-failed run can resume without re-scraping.
        # metafields dict is plain JSON; price (Decimal) needs str.
        with CACHE_PATH.open("w") as fh:
            for r in parsed:
                serializable = {**r, "price": str(r["price"]) if r["price"] is not None else None}
                fh.write(json.dumps(serializable) + "\n")
        print(f"[info] cached parse output to {CACHE_PATH}")

    # When loading from cache, price was str()-roundtripped — restore as Decimal.
    # Older cache also stored image_url as the raw dict instead of the src
    # string; normalize that here to avoid re-scraping.
    # Re-derive business_line on every load: routing rules may have evolved
    # since the cache was written.
    for r in parsed:
        if isinstance(r.get("price"), str):
            try:
                r["price"] = Decimal(r["price"])
            except (InvalidOperation, TypeError):
                r["price"] = None
        img = r.get("image_url")
        if isinstance(img, dict):
            r["image_url"] = img.get("src") or img.get("url")
        mf = r.get("metafields") or {}
        url = r.get("url") or ""
        has_construct = bool(_strip(mf.get("carConstruct")))
        if has_construct:
            r["business_line"] = "CAR-T/CAR-NK"
        elif LNP_URL_PAT.search(url):
            r["business_line"] = "mRNA-LNP"
        elif CART_URL_PAT.search(url):
            r["business_line"] = "Other Products"

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT catalog_no FROM product_catalog "
                "WHERE business_line IN ('CAR-T/CAR-NK', 'mRNA-LNP')"
            )
            existing = {r[0] for r in cur.fetchall()}

            new_records = [r for r in parsed if r["sku"] not in existing]
            print(f"[info] DB existing CAR-T+LNP: {len(existing)}; "
                  f"web-parsed: {len(parsed)}; new to insert: {len(new_records)}")
            for rec in new_records:
                print(f"   NEW {rec['sku']:14s} {rec['business_line']:14s} {rec['title'][:60]}")

            inserted_cart = 0
            inserted_lnp = 0
            inserted_other = 0
            for rec in new_records:
                parent_row = _build_parent_row(rec)
                try:
                    cur.execute(PARENT_INSERT, parent_row)
                except Exception:
                    print(f"[ERR] PARENT_INSERT failed for {rec['sku']}; row types: "
                          f"{[(k, type(v).__name__) for k, v in parent_row.items()]}")
                    raise
                product_id = cur.fetchone()[0]
                bl = rec["business_line"]
                if bl == "CAR-T/CAR-NK":
                    child_row = _build_cart_child(rec) | {"product_id": product_id}
                    cur.execute(CART_CHILD_INSERT, child_row)
                    inserted_cart += 1
                elif bl == "mRNA-LNP":
                    child_row = _build_lnp_child(rec) | {"product_id": product_id}
                    cur.execute(LNP_CHILD_INSERT, child_row)
                    inserted_lnp += 1
                else:
                    inserted_other += 1

            print(f"[ok] inserted CAR-T: {inserted_cart}, mRNA-LNP: {inserted_lnp}, Other: {inserted_other}")

            cur.execute(
                "SELECT business_line, COUNT(*) FROM product_catalog "
                "WHERE business_line IN ('CAR-T/CAR-NK', 'mRNA-LNP') GROUP BY business_line"
            )
            for bl, n in cur.fetchall():
                print(f"[verify] {bl}: {n}")

            if not apply:
                conn.rollback()
                print("\n[DRY RUN] rolled back. Re-run with --apply to commit.")
            else:
                conn.commit()
                print("\n[COMMITTED]")


if __name__ == "__main__":
    main()
