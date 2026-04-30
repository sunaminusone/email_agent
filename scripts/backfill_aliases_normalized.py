#!/usr/bin/env python3
"""Backfill product_catalog.aliases_normalized from product_catalog.aliases.

Why a Python script (not pure SQL): normalize_object_alias has a special
rule (`\\b6\\s*x?\\s*his\\b → 6xhis` and the unicode `×→x` / `&→ and`
substitutions) that is brittle to express identically in SQL. Single
Python source of truth keeps writer (importer / expand scripts) and
backfill in lockstep.

Idempotent: re-running yields the same aliases_normalized values; rows
already in sync are still rewritten (cheap, ~17k rows). Use --dry-run to
preview length stats without writing.

Apply order:
   1. psql -f sql/migrations/001_pre_backfill_business_line_key_aliases_normalized.sql
   2. python scripts/backfill_aliases_normalized.py             # dry-run by default
   3. python scripts/backfill_aliases_normalized.py --apply
   4. psql -f sql/migrations/002_post_backfill_constraints.sql
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    raise SystemExit("psycopg not installed. pip install -r requirements.txt")

from src.objects.normalizers import clean_text, normalize_object_alias


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill product_catalog.aliases_normalized from .aliases."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to PG. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per UPDATE batch (default 500).",
    )
    return parser.parse_args()


def normalize_with_fallback(alias: object) -> tuple[str, str]:
    """Normalize one alias; fall back to lower(clean_text(...)) if empty.

    Returns (normalized_value, source_tag) where source_tag is one of
    "normalized" / "fallback" / "empty_source" — tag is for stats only.

    Avoids writing '' into aliases_normalized so the GIN index doesn't end
    up with a junk empty-string element that would falsely match queries.
    Length invariant (CHECK in migration 002) is preserved by always
    returning exactly one string per input position.
    """
    primary = normalize_object_alias(alias)
    if primary:
        return primary, "normalized"
    fallback = clean_text(alias).lower()
    if fallback:
        return fallback, "fallback"
    # Source alias was None / "" / pure punctuation — preserve a non-null
    # marker so length stays equal but cannot collide with real aliases.
    # CHECK only enforces length, not non-emptiness, so we pick a stable
    # sentinel that is obvious in dumps but won't be queried.
    return "__empty__", "empty_source"


def normalize_alias_list(aliases: list[str]) -> tuple[list[str], dict[str, int]]:
    """Normalize each alias preserving length; return values + per-source counts."""
    out: list[str] = []
    counts: dict[str, int] = {"normalized": 0, "fallback": 0, "empty_source": 0}
    for alias in aliases:
        value, tag = normalize_with_fallback(alias)
        out.append(value)
        counts[tag] += 1
    return out, counts


def main() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set in .env")

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM product_catalog")
            total_rows = cur.fetchone()[0]

            cur.execute("SELECT id, aliases FROM product_catalog ORDER BY id")
            rows = cur.fetchall()

        # Compute normalized form for every row
        update_rows: list[tuple[str, list[str]]] = []
        length_mismatches = 0
        agg_counts = {"normalized": 0, "fallback": 0, "empty_source": 0}
        sample_with_fallback: tuple[str, list[str], list[str]] | None = None
        for row_id, aliases in rows:
            if not isinstance(aliases, list):
                aliases = []
            normalized, counts = normalize_alias_list(aliases)
            for k, v in counts.items():
                agg_counts[k] += v
            if len(normalized) != len(aliases):
                length_mismatches += 1
            if sample_with_fallback is None and counts["fallback"] > 0:
                sample_with_fallback = (str(row_id), aliases, normalized)
            update_rows.append((str(row_id), normalized))

        # Sample dump
        sample_idx = min(3, len(update_rows) - 1)
        if update_rows:
            print(f"Sample (row index {sample_idx}):")
            print(f"  id={update_rows[sample_idx][0]}")
            print(f"  aliases     ={rows[sample_idx][1]}")
            print(f"  normalized  ={update_rows[sample_idx][1]}")
        if sample_with_fallback is not None:
            sid, src, norm = sample_with_fallback
            print(f"\nFirst row using fallback:")
            print(f"  id={sid}")
            print(f"  aliases    ={src}")
            print(f"  normalized ={norm}")

        print()
        print(f"Total rows: {total_rows}")
        print(f"Rows to update: {len(update_rows)}")
        print(f"Length mismatches (would violate CHECK): {length_mismatches}")
        print(f"Per-element source counts:")
        print(f"  normalized   : {agg_counts['normalized']}")
        print(f"  fallback     : {agg_counts['fallback']}    (normalize_object_alias returned '', used clean_text+lower)")
        print(f"  empty_source : {agg_counts['empty_source']}    (source was null/empty/pure-punct, written as '__empty__')")

        if not args.apply:
            print("\n--dry-run (no writes). Re-run with --apply to commit.")
            return 0

        print(f"\nApplying in batches of {args.batch_size}...")
        with conn.cursor() as cur:
            for batch_start in range(0, len(update_rows), args.batch_size):
                batch = update_rows[batch_start:batch_start + args.batch_size]
                cur.executemany(
                    "UPDATE product_catalog SET aliases_normalized = %s WHERE id = %s",
                    [(Jsonb(normalized), row_id) for row_id, normalized in batch],
                )
                print(f"  {min(batch_start + args.batch_size, len(update_rows))}/{len(update_rows)}")
            conn.commit()

        # Verify length invariant in PG (preview of what CHECK will enforce)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM product_catalog
                WHERE jsonb_array_length(aliases) != jsonb_array_length(aliases_normalized)
            """)
            mismatch_after = cur.fetchone()[0]
        print(f"\nPost-apply length mismatches: {mismatch_after} (must be 0 for migration 002)")
        if mismatch_after > 0:
            print("ERROR: backfill produced length mismatches. Investigate before running migration 002.")
            return 1

    print("\nDone. Next step: psql -f sql/migrations/002_post_backfill_constraints.sql")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
