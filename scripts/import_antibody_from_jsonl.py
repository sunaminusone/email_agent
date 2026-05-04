#!/usr/bin/env python3
"""Import antibody web JSONL into product_catalog + antibody_product_catalog.

B2' of the antibody web-as-source-of-truth plan; replaces the legacy xlsx
import path (scripts/import_product_catalog.py) for the antibody business
line. See memory project_antibody_web_enrichment_plan.md.

CTI write pattern
-----------------
Each web record yields two rows in one transaction:
  1. product_catalog — shared columns (catalog_no / business_line='Antibody'
     / record_type / name / price / size / aliases / applications / etc.)
  2. antibody_product_catalog — antibody-only columns (host / isotype /
     dilutions / immunogen / formulation / storage / description_html /
     references_text / raw_metafields / etc.)

UPSERT semantics: ON CONFLICT (catalog_no) DO UPDATE on parent;
ON CONFLICT (product_id) DO UPDATE on child. Re-running this script is
idempotent — values get refreshed, ids stay stable, FK CASCADE preserves
the link.

Source-of-truth note
--------------------
This script assumes the parent table is empty for antibody business_line
(or at least that any pre-existing antibody rows came from the same web
import) — the new web data REPLACES the legacy xlsx-sourced antibody rows.
For the initial cutover, run `--wipe-antibody` first to delete legacy
antibody rows from the parent (CASCADE removes any orphaned child rows),
then run import.

Usage
-----
    # Dry-run — parse JSONL, map to row dicts, print stats. No DB write.
    python scripts/import_antibody_from_jsonl.py \\
        --jsonl /tmp/promab_antibody.jsonl

    # Apply — wipe existing antibody rows from parent, then write new data.
    python scripts/import_antibody_from_jsonl.py \\
        --jsonl /tmp/promab_antibody.jsonl \\
        --apply --wipe-antibody
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover
    psycopg = None
    Jsonb = None


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.objects.normalizers import clean_text as _clean_text
from src.objects.normalizers import normalize_object_alias as _normalize_object_alias


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BUSINESS_LINE = "Antibody"
SEQUENCE_SENTINEL = "N"  # web's "no sequence available" placeholder


def jsonb(value: Any) -> Any:
    if Jsonb is None:
        return value
    return Jsonb(value)


def _norm_alias(alias: object) -> str:
    """Mirror import_product_catalog.normalize_alias_with_fallback. Returns
    a non-empty string so the chk_aliases_normalized_length CHECK holds."""
    primary = _normalize_object_alias(alias)
    if primary:
        return primary
    fallback = _clean_text(alias).lower()
    return fallback or "__empty__"


def _strip(value: Any) -> str | None:
    """Coerce to a stripped string or None. Empty strings → None."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _split_list(raw: Any, separator: str) -> list[str]:
    """Split a delimited web string into a clean list of tokens.

    Web data uses two conventions:
      * aliases   : "LAP; CRP2; TCF5; IL6DBP" — ';' separated
      * application / speciesReactivity : "WB, ELISA" — ',' separated
    """
    if not raw:
        return []
    parts = [p.strip() for p in str(raw).split(separator)]
    return [p for p in parts if p]


def _split_aliases(raw: Any) -> list[str]:
    """Aliases use mixed separators across the catalog: 87% are ';'-separated
    (the dominant convention), 0.6% use ',' only (e.g. 20338 "LFS1, TRP53,
    TP53"), and a few records use both — typically ';' as outer separator
    with ',' inside individual alias names (e.g. "inhibin, alpha"). Strategy:
    if ';' is present, split on ';' (preserves comma-inside-name); otherwise
    split on ','.
    """
    if not raw:
        return []
    s = str(raw)
    sep = ";" if ";" in s else ","
    return _split_list(s, sep)


def _cheapest_variant(variants: list[dict] | None) -> dict | None:
    """Pick the variant with the lowest non-zero price.

    Multi-size antibody variants are rare on the web (most are single-size,
    e.g. "100μl"); when they exist (e.g. "100μl" / "500μl") we keep the
    cheapest as the displayed price + size. Future enhancement: stuff the
    full variant list into product_catalog.price_variants.
    """
    priced = []
    for v in variants or []:
        raw = v.get("price")
        if raw in (None, "", "0", "0.0", "0.00"):
            continue
        try:
            price = Decimal(str(raw))
        except (InvalidOperation, TypeError):
            continue
        priced.append((price, v))
    if not priced:
        return None
    priced.sort(key=lambda t: t[0])
    return priced[0][1]


def _all_priced_variants(variants: list[dict] | None) -> list[dict]:
    """Return every variant that has a real positive price, in price order.
    Used to build price_variants JSONB when the product is multi-size."""
    out = []
    for v in variants or []:
        raw = v.get("price")
        try:
            price = Decimal(str(raw))
        except (InvalidOperation, TypeError):
            continue
        if price <= 0:
            continue
        out.append({"size": v.get("title") or "", "price": str(price)})
    out.sort(key=lambda d: Decimal(d["price"]))
    return out


# ---------------------------------------------------------------------------
# Mapping JSONL → (parent_row, child_row)
# ---------------------------------------------------------------------------
def map_record(rec: dict[str, Any]) -> tuple[dict, dict] | None:
    """Map one JSONL record to (parent_dict, child_dict). Returns None if
    the record is unusable (no catalog_no)."""
    catalog_no = _strip(rec.get("catalog_no"))
    if not catalog_no:
        return None
    catalog_no = catalog_no.upper()

    metafields = rec.get("metafields") or {}
    title = _strip(rec.get("title"))
    if not title:
        return None  # name is NOT NULL on parent

    cheapest = _cheapest_variant(rec.get("variants"))
    price = None
    size = None
    if cheapest is not None:
        try:
            price = Decimal(str(cheapest.get("price")))
        except (InvalidOperation, TypeError):
            price = None
        size = _strip(cheapest.get("title"))

    all_priced = _all_priced_variants(rec.get("variants"))
    price_variants = all_priced if len(all_priced) > 1 else None

    aliases_list = _split_aliases(metafields.get("aliases"))
    applications_list = _split_list(metafields.get("application"), ",")
    species_list = _split_list(metafields.get("speciesReactivity"), ",")

    images = rec.get("images") or []
    image_url = images[0] if images else None
    tags = rec.get("tags") or []

    # ---- parent row ----
    parent: dict[str, Any] = {
        "catalog_no":         catalog_no,
        "business_line":      BUSINESS_LINE,
        "record_type":        _strip(metafields.get("type")),         # "Rabbit Polyclonal"
        "name":               title,
        "target_antigen":     None,                                    # left NULL — not provided on web; future regex from name
        "price":              price,
        "price_variants":     jsonb(price_variants) if price_variants else None,
        "currency":           "USD",
        "size":               size,
        "lead_time_text":     None,                                    # web doesn't expose it; CSR fills per-quote
        "aliases":            jsonb(aliases_list),
        "aliases_normalized": jsonb([_norm_alias(a) for a in aliases_list]),
        "applications":       jsonb(applications_list),
        "species_reactivity": jsonb(species_list),
        "web_tags":           jsonb(list(tags)),
        "attributes":         jsonb({}),                               # antibody fields go to child table, not attributes
        "image_url":          image_url,
        "source_url":         _strip(rec.get("source_url")),
        "web_handle":         _strip(rec.get("handle")),
        "is_active":          True,
        "last_synced_at":     None,                                    # set to NOW() in SQL via DEFAULT-style column
    }

    # ---- child row (antibody facet) ----
    sequence = _strip(metafields.get("sequence"))
    if sequence == SEQUENCE_SENTINEL:
        sequence = None

    child: dict[str, Any] = {
        "host":                 _strip(metafields.get("host")),
        "isotype":              _strip(metafields.get("isotype")),
        "clone":                _strip(metafields.get("clone")),
        "molecular_weight":     _strip(metafields.get("molecularWeight")),
        "gene_id":              _strip(metafields.get("entrezGeneid")),
        "sequence":             sequence,
        "elisa_dilution":       _strip(metafields.get("elisa")),
        "wb_dilution":          _strip(metafields.get("westernBlotting")),
        "fcm_dilution":         _strip(metafields.get("fcm")),
        "ihc_dilution":         _strip(metafields.get("ihc")),
        "icc_dilution":         _strip(metafields.get("icc")),
        "immunogen":            _strip(metafields.get("immunogen")),
        "formulation":          _strip(metafields.get("formulation")),
        "storage":              _strip(metafields.get("storage")),
        "shipping_information": _strip(metafields.get("shippingInformation")),
        "description_html":     _strip(rec.get("body_html")),
        "references_text":      _strip(metafields.get("references")),
        "raw_metafields":       jsonb(dict(metafields)),
    }

    return parent, child


# ---------------------------------------------------------------------------
# JSONL streaming
# ---------------------------------------------------------------------------
def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    seen_catalog: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for line_num, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"[warn] line {line_num}: skipping JSON decode error: {exc}", file=sys.stderr)
                continue
            cn = (rec.get("catalog_no") or "").strip().upper()
            if not cn:
                continue
            if cn in seen_catalog:
                # Same catalog_no listed under multiple categories
                # (mostly cross-listings). Keep the first occurrence to
                # mirror legacy enrich_antibody_xlsx behaviour.
                continue
            seen_catalog.add(cn)
            yield rec


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------
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
    ON CONFLICT (catalog_no) DO UPDATE SET
        business_line      = EXCLUDED.business_line,
        record_type        = EXCLUDED.record_type,
        name               = EXCLUDED.name,
        target_antigen     = EXCLUDED.target_antigen,
        price              = EXCLUDED.price,
        price_variants     = EXCLUDED.price_variants,
        currency           = EXCLUDED.currency,
        size               = EXCLUDED.size,
        lead_time_text     = EXCLUDED.lead_time_text,
        aliases            = EXCLUDED.aliases,
        aliases_normalized = EXCLUDED.aliases_normalized,
        applications       = EXCLUDED.applications,
        species_reactivity = EXCLUDED.species_reactivity,
        web_tags           = EXCLUDED.web_tags,
        attributes         = EXCLUDED.attributes,
        image_url          = EXCLUDED.image_url,
        source_url         = EXCLUDED.source_url,
        web_handle         = EXCLUDED.web_handle,
        is_active          = EXCLUDED.is_active,
        last_synced_at     = CURRENT_TIMESTAMP
    RETURNING id;
"""

CHILD_UPSERT = """
    INSERT INTO antibody_product_catalog (
        product_id, host, isotype, clone, molecular_weight, gene_id, sequence,
        elisa_dilution, wb_dilution, fcm_dilution, ihc_dilution, icc_dilution,
        immunogen, formulation, storage, shipping_information,
        description_html, references_text, raw_metafields
    ) VALUES (
        %(product_id)s, %(host)s, %(isotype)s, %(clone)s, %(molecular_weight)s, %(gene_id)s, %(sequence)s,
        %(elisa_dilution)s, %(wb_dilution)s, %(fcm_dilution)s, %(ihc_dilution)s, %(icc_dilution)s,
        %(immunogen)s, %(formulation)s, %(storage)s, %(shipping_information)s,
        %(description_html)s, %(references_text)s, %(raw_metafields)s
    )
    ON CONFLICT (product_id) DO UPDATE SET
        host                 = EXCLUDED.host,
        isotype              = EXCLUDED.isotype,
        clone                = EXCLUDED.clone,
        molecular_weight     = EXCLUDED.molecular_weight,
        gene_id              = EXCLUDED.gene_id,
        sequence             = EXCLUDED.sequence,
        elisa_dilution       = EXCLUDED.elisa_dilution,
        wb_dilution          = EXCLUDED.wb_dilution,
        fcm_dilution         = EXCLUDED.fcm_dilution,
        ihc_dilution         = EXCLUDED.ihc_dilution,
        icc_dilution         = EXCLUDED.icc_dilution,
        immunogen            = EXCLUDED.immunogen,
        formulation          = EXCLUDED.formulation,
        storage              = EXCLUDED.storage,
        shipping_information = EXCLUDED.shipping_information,
        description_html     = EXCLUDED.description_html,
        references_text      = EXCLUDED.references_text,
        raw_metafields       = EXCLUDED.raw_metafields;
"""


def wipe_antibody_rows(conn) -> int:
    """Delete existing antibody rows from product_catalog.

    Child rows are removed automatically by ON DELETE CASCADE on the FK.
    Returns the number of parent rows deleted.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM product_catalog WHERE business_line ~* 'antibody'"
        )
        return cur.rowcount


def write_records(conn, records: list[tuple[dict, dict]]) -> tuple[int, int]:
    """Insert all (parent, child) pairs in one transaction. Returns
    (parents_written, children_written)."""
    parents_written = 0
    children_written = 0
    with conn.cursor() as cur:
        for parent, child in records:
            cur.execute(PARENT_INSERT, parent)
            row = cur.fetchone()
            if row is None:
                continue
            product_id = row[0]
            child_with_fk = {"product_id": product_id, **child}
            cur.execute(CHILD_UPSERT, child_with_fk)
            parents_written += 1
            children_written += 1
    return parents_written, children_written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jsonl", required=True, help="Path to scrape_promab_prices.py JSONL output.")
    p.add_argument("--apply", action="store_true",
                   help="Actually write to PG. Without this flag, the script only parses + reports.")
    p.add_argument("--wipe-antibody", action="store_true",
                   help="Before writing, DELETE existing antibody rows from product_catalog "
                        "(child rows go via FK CASCADE). Use on the initial cutover.")
    p.add_argument("--limit", type=int, default=0,
                   help="Process only the first N JSONL records (debug / smoke).")
    p.add_argument("--database-url", default=None,
                   help="PG connection string. Falls back to DATABASE_URL env var.")
    return p.parse_args()


def get_connection_string(explicit: str | None) -> str:
    if explicit:
        return explicit
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("Missing DATABASE_URL — set it in .env or pass --database-url.")
    return url


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")

    src = Path(args.jsonl)
    if not src.exists():
        print(f"[error] JSONL not found: {src}", file=sys.stderr)
        return 2

    print(f"[info] reading JSONL: {src}")
    records: list[tuple[dict, dict]] = []
    n_read = 0
    n_skipped = 0
    for rec in iter_jsonl(src):
        n_read += 1
        if args.limit and n_read > args.limit:
            break
        mapped = map_record(rec)
        if mapped is None:
            n_skipped += 1
            continue
        records.append(mapped)

    n = len(records)
    print(f"[info] usable records: {n} (read={n_read}, skipped={n_skipped})")

    # Plain-Python summary (no Jsonb introspection needed)
    n_with_price       = sum(1 for p, _ in records if p["price"] is not None)
    n_multi_size       = sum(1 for p, _ in records if p["price_variants"] is not None)
    n_with_host        = sum(1 for _, c in records if c["host"])
    n_with_immunogen   = sum(1 for _, c in records if c["immunogen"])
    n_with_elisa       = sum(1 for _, c in records if c["elisa_dilution"])
    n_with_wb          = sum(1 for _, c in records if c["wb_dilution"])
    n_with_fcm         = sum(1 for _, c in records if c["fcm_dilution"])
    n_with_ihc         = sum(1 for _, c in records if c["ihc_dilution"])
    n_with_gene        = sum(1 for _, c in records if c["gene_id"])
    n_with_sequence    = sum(1 for _, c in records if c["sequence"])
    n_with_description = sum(1 for _, c in records if c["description_html"])

    print(f"[stats] price filled        : {n_with_price}/{n}")
    print(f"[stats] multi-size variants : {n_multi_size}/{n}")
    print(f"[stats] host filled         : {n_with_host}/{n}")
    print(f"[stats] immunogen filled    : {n_with_immunogen}/{n}")
    print(f"[stats] gene_id filled      : {n_with_gene}/{n}")
    print(f"[stats] sequence filled     : {n_with_sequence}/{n}")
    print(f"[stats] elisa_dilution      : {n_with_elisa}/{n}")
    print(f"[stats] wb_dilution         : {n_with_wb}/{n}")
    print(f"[stats] fcm_dilution        : {n_with_fcm}/{n}")
    print(f"[stats] ihc_dilution        : {n_with_ihc}/{n}")
    print(f"[stats] description_html    : {n_with_description}/{n}")

    if not args.apply:
        print("[info] dry-run (no DB write). Re-run with --apply to write.")
        return 0

    if psycopg is None:
        print("[error] psycopg not installed. `pip install -r requirements.txt` first.", file=sys.stderr)
        return 2

    conn_str = get_connection_string(args.database_url)
    with psycopg.connect(conn_str) as conn:
        if args.wipe_antibody:
            deleted = wipe_antibody_rows(conn)
            print(f"[apply] wiped existing antibody parent rows: {deleted}")

        parents, children = write_records(conn, records)
        conn.commit()
        print(f"[apply] wrote parent rows : {parents}")
        print(f"[apply] wrote child rows  : {children}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
