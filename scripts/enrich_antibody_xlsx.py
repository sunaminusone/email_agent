#!/usr/bin/env python3
"""Join the antibody web JSONL (B1 output) into antibody_products.xlsx.

B2 of the antibody web enrichment plan; see memory
project_antibody_web_enrichment_plan.md.

Strategy
--------
1. Read both sheets of the source xlsx (Monoclonal + Polyclonal).
2. Stream the JSONL into a {catalog_no: record} index.
3. For each xlsx row: if catalog_no is in the index,
   * overwrite ``cost`` with the cheapest variant price (the column was
     0% filled in the source);
   * add ``web_*`` columns for everything the front-end exposes that
     xlsx doesn't already carry (immunogen, formulation, storage,
     dilutions, molecular weight, references, description, image URL,
     source URL).
4. Write to ``antibody_products_enriched.xlsx`` in the same directory,
   preserving sheet structure. Original file untouched.

Rows whose catalog_no isn't in the JSONL keep their existing values and
get NULL in the new web_* columns — that's expected: only ~24% of the
xlsx (4080/17016) has a public web page.

Usage
-----
    python scripts/enrich_antibody_xlsx.py \\
        --xlsx data/processed/antibody_products.xlsx \\
        --jsonl /tmp/promab_antibody.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


# Column additions. Keys are the xlsx column name; values are
# (jsonl_path, transform). jsonl_path is dotted into the parsed dict.
WEB_COLUMNS: dict[str, tuple[str, callable]] = {
    "web_price":            ("__cheapest_variant_price__", lambda x: x),
    "web_size":             ("__cheapest_variant_size__",  lambda x: x),
    "web_title":            ("title",                       lambda x: x),
    "web_immunogen":        ("metafields.immunogen",        lambda x: x),
    "web_formulation":      ("metafields.formulation",      lambda x: x),
    "web_storage":          ("metafields.storage",          lambda x: x),
    "web_elisa_dilution":   ("metafields.elisa",            lambda x: x),
    "web_wb_dilution":      ("metafields.westernBlotting",  lambda x: x),
    "web_molecular_weight": ("metafields.molecularWeight",  lambda x: x),
    "web_species_reactivity":("metafields.speciesReactivity", lambda x: x),
    "web_host":             ("metafields.host",             lambda x: x),
    "web_isotype":          ("metafields.isotype",          lambda x: x),
    "web_application":      ("metafields.application",      lambda x: x),
    "web_aliases":          ("metafields.aliases",          lambda x: x),
    "web_clone":            ("metafields.clone",            lambda x: x),
    "web_type":             ("metafields.type",             lambda x: x),
    "web_sequence":         ("metafields.sequence",         lambda x: x),
    "web_references":       ("metafields.references",       lambda x: x),
    "web_shipping_info":    ("metafields.shippingInformation", lambda x: x),
    "web_body_html":        ("body_html",                    lambda x: x),
    "web_image_url":        ("__first_image__",              lambda x: x),
    "web_source_url":       ("source_url",                   lambda x: x),
}


def _walk(record: dict, path: str):
    """Look up a dotted path inside the JSONL record. Synthetic paths
    (``__cheapest_variant_price__``, ``__cheapest_variant_size__``,
    ``__first_image__``) bypass the dotted walk and use computed values
    pre-attached to the record."""
    if path.startswith("__"):
        return record.get(path)
    cur = record
    for seg in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(seg)
    return cur


def _cheapest_variant(variants: list[dict]) -> dict | None:
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


def load_jsonl(path: Path) -> dict[str, dict]:
    """Read JSONL into {catalog_no: record}. When the same catalog_no
    appears more than once (unlikely but possible — e.g. duplicate
    listings under multiple categories), keep the first."""
    index: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (rec.get("catalog_no") or "").strip().upper()
            if not key or key in index:
                continue
            cheapest = _cheapest_variant(rec.get("variants") or [])
            if cheapest is not None:
                rec["__cheapest_variant_price__"] = cheapest.get("price")
                rec["__cheapest_variant_size__"] = cheapest.get("title") or ""
            else:
                rec["__cheapest_variant_price__"] = None
                rec["__cheapest_variant_size__"] = None
            images = rec.get("images") or []
            rec["__first_image__"] = images[0] if images else None
            index[key] = rec
    return index


def enrich_sheet(df: pd.DataFrame, web: dict[str, dict]) -> tuple[pd.DataFrame, int]:
    """Return (enriched DataFrame, row count matched by catalog_no)."""
    matched = 0
    new_cols: dict[str, list] = {col: [None] * len(df) for col in WEB_COLUMNS}
    cost_col_index = list(df.columns).index("cost") if "cost" in df.columns else None
    cost_values = list(df["cost"]) if cost_col_index is not None else None

    for i, raw_no in enumerate(df["Catalog#"].astype(str)):
        key = raw_no.strip().upper()
        rec = web.get(key)
        if rec is None:
            continue
        matched += 1
        for col, (path, fn) in WEB_COLUMNS.items():
            value = _walk(rec, path)
            if value is None or value == "":
                continue
            new_cols[col][i] = fn(value)
        # Overwrite the empty cost column with the cheapest variant price.
        if cost_values is not None:
            price = rec.get("__cheapest_variant_price__")
            if price is not None:
                cost_values[i] = price

    out = df.copy()
    if cost_values is not None:
        out["cost"] = cost_values
    for col, values in new_cols.items():
        out[col] = values
    return out, matched


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--xlsx",
        default=str(ROOT / "data" / "processed" / "antibody_products.xlsx"),
        help="Source antibody xlsx (read-only, will not be modified).",
    )
    p.add_argument("--jsonl", required=True, help="JSONL produced by scrape_promab_prices.py.")
    p.add_argument(
        "--out",
        default="",
        help="Destination enriched xlsx (default: <xlsx-stem>_enriched.xlsx beside the source).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    src = Path(args.xlsx)
    if not src.exists():
        print(f"[error] source xlsx not found: {src}", file=sys.stderr)
        return 2
    out_path = Path(args.out) if args.out else src.with_name(src.stem + "_enriched.xlsx")

    print(f"[info] loading JSONL: {args.jsonl}")
    web = load_jsonl(Path(args.jsonl))
    print(f"[info] JSONL records: {len(web)} unique catalog_no")

    sheets = pd.read_excel(src, sheet_name=None)
    print(f"[info] xlsx sheets: {list(sheets.keys())}")
    enriched: dict[str, pd.DataFrame] = {}
    matched_keys: set[str] = set()
    for sheet, df in sheets.items():
        out_df, matched = enrich_sheet(df, web)
        enriched[sheet] = out_df
        print(f"[info] sheet={sheet!r}: {matched}/{len(df)} matched ({100*matched/len(df):.1f}%)")
        for raw_no in df["Catalog#"].astype(str):
            key = raw_no.strip().upper()
            if key in web:
                matched_keys.add(key)

    # Surface web catalog_no that didn't match any xlsx row. This is real
    # data discovery — the storefront sometimes carries products in
    # numbering ranges the source xlsx doesn't (e.g. 10000-series 5-digit
    # antibodies vs xlsx's P-prefix Polyclonals).
    unmatched_keys = sorted(set(web.keys()) - matched_keys)
    if unmatched_keys:
        rows = []
        for key in unmatched_keys:
            rec = web[key]
            row = {"Catalog#": key, "title": rec.get("title", "")}
            for col, (path, fn) in WEB_COLUMNS.items():
                value = _walk(rec, path)
                row[col] = fn(value) if value not in (None, "") else None
            rows.append(row)
        enriched["Web Only (no xlsx match)"] = pd.DataFrame(rows)
        print(f"[info] web-only catalog_no (no xlsx row): {len(unmatched_keys)} → 'Web Only' sheet")

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for sheet, out_df in enriched.items():
            out_df.to_excel(writer, sheet_name=sheet, index=False)
    print(f"[info] wrote enriched xlsx: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
