#!/usr/bin/env python3
"""Backfill target_antigen + canonical-symbol aliases for antibody rows.

Background
----------
The web import (import_antibody_from_jsonl.py) leaves target_antigen NULL
and only stores metafields.aliases as the alias list. The canonical gene
symbol (typically the first token of the product title — e.g. "SDHA" in
"SDHA Primary Antibody") is never written to either column.

Effect on retrieval: tier_2 alias_lookup (jsonb GIN ?| over
aliases_normalized) misses customer queries like "SDHA antibody" → falls
to tier_3 fuzzy_lookup, whose similarity-OR branch surfaces unrelated
Mouse Monoclonal antibodies as noise.

This script extracts the canonical symbol from the product name and:
  1. Sets target_antigen (only if currently empty — never overwrite)
  2. Appends the symbol to aliases (case-preserved) AND
     aliases_normalized (lowercased) — both de-duped against existing
     entries via normalize_object_alias.

Idempotent: a second run finds the symbol already in aliases and writes
nothing.

Usage
-----
    # Dry-run — print extraction stats and write nothing.
    python scripts/backfill_antibody_target_aliases.py

    # Apply.
    python scripts/backfill_antibody_target_aliases.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg
from psycopg.types.json import Jsonb

from src.objects.antibody_names import extract_canonical_symbols
from src.objects.normalizers import normalize_object_alias


# ---------------------------------------------------------------------------
# Per-row update planning
# ---------------------------------------------------------------------------
def plan_update(
    *,
    name: str,
    target_antigen: str | None,
    aliases: list[str],
    aliases_normalized: list[str],
) -> tuple[str | None, list[str], list[str]] | None:
    """Compute new (target_antigen, aliases, aliases_normalized) tuple, or
    None if no change.

    Rules:
      * target_antigen: only set if currently empty/null. Never overwrite.
      * aliases: append each extracted candidate not already present
        (compared by normalize_object_alias). Preserve original order.
      * aliases_normalized: derived from aliases via normalize_object_alias,
        kept in lockstep.
    """
    candidates = extract_canonical_symbols(name)
    if not candidates:
        return None

    existing_normalized = {normalize_object_alias(a) for a in aliases}

    new_aliases = list(aliases)
    appended_norms: list[str] = []
    for cand in candidates:
        n = normalize_object_alias(cand)
        if not n or n in existing_normalized:
            continue
        existing_normalized.add(n)
        new_aliases.append(cand)
        appended_norms.append(n)

    new_target = target_antigen
    if not (target_antigen or "").strip():
        new_target = candidates[0]

    if new_target == target_antigen and not appended_norms:
        return None

    new_aliases_norm = list(aliases_normalized)
    for n in appended_norms:
        if n not in new_aliases_norm:
            new_aliases_norm.append(n)

    return new_target, new_aliases, new_aliases_norm


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------
SELECT_SQL = """
    SELECT catalog_no, name, target_antigen,
           COALESCE(aliases, '[]'::jsonb)            AS aliases,
           COALESCE(aliases_normalized, '[]'::jsonb) AS aliases_normalized
      FROM product_catalog
     WHERE business_line = 'Antibody'
"""

UPDATE_SQL = """
    UPDATE product_catalog
       SET target_antigen     = %(target_antigen)s,
           aliases            = %(aliases)s,
           aliases_normalized = %(aliases_normalized)s
     WHERE catalog_no = %(catalog_no)s
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write to PG. Without this, runs as dry-run.")
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    url = args.database_url or os.getenv("DATABASE_URL")
    if not url:
        print("[error] DATABASE_URL missing.", file=sys.stderr)
        return 2

    rows_total = 0
    rows_target_set = 0
    rows_aliases_changed = 0
    rows_no_change = 0
    rows_no_extraction = 0
    updates: list[dict] = []

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(SELECT_SQL)
            rows = cur.fetchall()

        for catalog_no, name, target_antigen, aliases, aliases_normalized in rows:
            rows_total += 1
            plan = plan_update(
                name=name,
                target_antigen=target_antigen,
                aliases=list(aliases or []),
                aliases_normalized=list(aliases_normalized or []),
            )
            if plan is None:
                if not extract_canonical_symbols(name):
                    rows_no_extraction += 1
                else:
                    rows_no_change += 1
                continue

            new_target, new_aliases, new_aliases_norm = plan
            if new_target != target_antigen:
                rows_target_set += 1
            if new_aliases != list(aliases or []):
                rows_aliases_changed += 1

            updates.append({
                "catalog_no": catalog_no,
                "target_antigen": new_target,
                "aliases": Jsonb(new_aliases),
                "aliases_normalized": Jsonb(new_aliases_norm),
            })

        print(f"[info] antibody rows scanned        : {rows_total}")
        print(f"[info] rows planned for update       : {len(updates)}")
        print(f"[info]   target_antigen newly set    : {rows_target_set}")
        print(f"[info]   aliases gained at least 1   : {rows_aliases_changed}")
        print(f"[info] rows already up-to-date       : {rows_no_change}")
        print(f"[info] rows with no extractable name : {rows_no_extraction}")

        if not args.apply:
            print("[info] dry-run; pass --apply to write. Sample of planned updates:")
            for u in updates[:5]:
                print(f"  [{u['catalog_no']}] target={u['target_antigen']!r}")
            return 0

        if not updates:
            print("[apply] nothing to do.")
            return 0

        with conn.cursor() as cur:
            cur.executemany(UPDATE_SQL, updates)
        conn.commit()
        print(f"[apply] wrote {len(updates)} rows.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
