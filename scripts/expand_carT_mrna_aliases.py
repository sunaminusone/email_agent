#!/usr/bin/env python3
"""Expand CAR-T and mRNA-LNP product aliases in product_catalog.

Why:
    Customer-facing alias forms missing from current catalog data:
      CAR-T : 'Anti-CD19 CAR-T', 'Anti-CD19 CAR', 'CD19 CAR' (口语)
              'huCD19 CAR-T' (humanized 简短形)
              'CD19/CD22 CAR-T', 'CD19+CD22 CAR-T' (dual target)
      mRNA-LNP: 'CD19 mRNA LNP', 'CD19 mRNA Lipid Nanoparticle', 'CD19 LNP mRNA'

    Layer B 此前在 product_registry 里走 entry.business_line == "car_t" 分支判断,
    但 RDS 里实际值是 'CAR-T/CAR-NK',永远走不到 → 一直 silent fallback。
    此脚本把扩展结果落到 PG aliases / aliases_normalized,
    脱离 in-memory expand 路径,与新 GIN(?|) lookup 直接对齐。

CAR-T 规则(business_line_key='car_t_car_nk' AND target_antigen IS NOT NULL
            AND target_antigen != 'Mock'):
    单 target T → {T} CAR / Anti-{T} CAR-T / Anti-{T} CAR
                  if aliases 里存在 hu{T}*scFv → +hu{T} CAR-T
    dual target (target_antigen 含 + 或 / → 拆 [T1, T2]):
        各 Ti 套单 target 规则
        组合: {T1}/{T2} CAR-T, {T1}+{T2} CAR-T,
              {T1}/{T2} CAR,   {T1}+{T2} CAR,
              Anti-{T1}/{T2} CAR-T

mRNA-LNP 规则(business_line_key='mrna_lnp' AND name ILIKE '%mRNA-LNP%'):
    name 里 'mRNA-LNP' 替换为:
        'mRNA LNP' / 'mRNA Lipid Nanoparticle' / 'LNP mRNA'

通用:
    - 默认 dry-run, --apply 才写
    - idempotent: 增量 merge(去重),aliases_normalized 同步重算
    - 写时保持 len(aliases) == len(aliases_normalized) (CHECK 不变)
    - 不修改 target='Mock' / target IS NULL 行
    - dual 不拆 & 也不拆 . (CLDN18.2 当 single)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:
    raise SystemExit("psycopg not installed. pip install -r requirements.txt")

from src.objects.normalizers import clean_text, normalize_object_alias


DUAL_TARGET_SPLIT = re.compile(r"\s*[+/]\s*")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="Write to PG. Without this flag, dry-run.")
    p.add_argument("--batch-size", type=int, default=200)
    p.add_argument("--limit", type=int, default=0, help="Process only first N matched rows (0 = all).")
    return p.parse_args()


def normalize_with_fallback(alias: object) -> str:
    """Mirror of scripts/backfill_aliases_normalized.normalize_with_fallback (value only)."""
    primary = normalize_object_alias(alias)
    if primary:
        return primary
    fallback = clean_text(alias).lower()
    if fallback:
        return fallback
    return "__empty__"


def split_targets(target: str) -> list[str]:
    """Split target_antigen on + and / only; preserve dots (CLDN18.2 stays single)."""
    parts = [t.strip() for t in DUAL_TARGET_SPLIT.split(target) if t.strip()]
    return parts


def has_humanized_construct(aliases: list[str], target: str) -> bool:
    """Detect if any alias starts with 'hu{target}' (e.g. 'huCD19scFv-...').

    Plain startswith is intentional: humanized constructs in real data are all
    of form 'hu{Target}scFv-...', and target tokens are short distinct strings
    (CD19/BCMA/CEA/CD47), so false positives like 'huCD194' don't exist.
    """
    if not target:
        return False
    pat = re.compile(rf"^hu{re.escape(target)}", re.IGNORECASE)
    return any(pat.search(a or "") for a in aliases)


def cart_aliases_for_single(target: str, *, humanized: bool) -> list[str]:
    out = [
        f"{target} CAR",
        f"Anti-{target} CAR-T",
        f"Anti-{target} CAR",
    ]
    if humanized:
        out.append(f"hu{target} CAR-T")
    return out


def cart_aliases_for_dual(t1: str, t2: str) -> list[str]:
    return [
        f"{t1}/{t2} CAR-T",
        f"{t1}+{t2} CAR-T",
        f"{t1}/{t2} CAR",
        f"{t1}+{t2} CAR",
        f"Anti-{t1}/{t2} CAR-T",
    ]


def generate_cart_additions(target: str, current_aliases: list[str]) -> list[str]:
    """Return new alias strings (not yet in current_aliases, case-insensitive)."""
    targets = split_targets(target)
    if not targets:
        return []

    candidates: list[str] = []
    for t in targets:
        candidates.extend(cart_aliases_for_single(t, humanized=has_humanized_construct(current_aliases, t)))

    if len(targets) == 2:
        candidates.extend(cart_aliases_for_dual(targets[0], targets[1]))

    existing_lower = {(a or "").strip().lower() for a in current_aliases}
    seen_lower: set[str] = set()
    additions: list[str] = []
    for c in candidates:
        key = c.strip().lower()
        if not key or key in existing_lower or key in seen_lower:
            continue
        seen_lower.add(key)
        additions.append(c)
    return additions


def generate_mrna_additions(name: str, current_aliases: list[str]) -> list[str]:
    if not name or "mRNA-LNP" not in name:
        return []
    replacements = ["mRNA LNP", "mRNA Lipid Nanoparticle", "LNP mRNA"]
    candidates = [name.replace("mRNA-LNP", repl) for repl in replacements]

    existing_lower = {(a or "").strip().lower() for a in current_aliases}
    seen_lower: set[str] = set()
    additions: list[str] = []
    for c in candidates:
        key = c.strip().lower()
        if not key or key in existing_lower or key in seen_lower:
            continue
        seen_lower.add(key)
        additions.append(c)
    return additions


def fetch_candidates(conn) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, catalog_no, name, target_antigen, business_line_key, aliases
            FROM product_catalog
            WHERE (
                business_line_key = 'car_t_car_nk'
                AND target_antigen IS NOT NULL
                AND target_antigen <> 'Mock'
            ) OR (
                business_line_key = 'mrna_lnp'
                AND name ILIKE '%%mRNA-LNP%%'
            )
            ORDER BY catalog_no
            """
        )
        return cur.fetchall()


def main() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set in .env")

    with psycopg.connect(dsn) as conn:
        rows = fetch_candidates(conn)
        if args.limit:
            rows = rows[: args.limit]

        updates: list[tuple[str, list[str], list[str]]] = []
        sample_cart: tuple[str, str, list[str]] | None = None
        sample_mrna: tuple[str, str, list[str]] | None = None
        cart_added = 0
        mrna_added = 0

        for r in rows:
            current_aliases = list(r["aliases"] or [])
            additions: list[str]
            if r["business_line_key"] == "car_t_car_nk":
                additions = generate_cart_additions(r["target_antigen"] or "", current_aliases)
                if additions and sample_cart is None:
                    sample_cart = (r["catalog_no"], r["target_antigen"], additions)
                cart_added += len(additions)
            else:
                additions = generate_mrna_additions(r["name"] or "", current_aliases)
                if additions and sample_mrna is None:
                    sample_mrna = (r["catalog_no"], r["name"], additions)
                mrna_added += len(additions)

            if not additions:
                continue

            new_aliases = current_aliases + additions
            new_normalized = [normalize_with_fallback(a) for a in new_aliases]
            assert len(new_aliases) == len(new_normalized)
            updates.append((str(r["id"]), new_aliases, new_normalized))

        print(f"Candidates scanned    : {len(rows)}")
        print(f"Rows to update        : {len(updates)}")
        print(f"  CAR-T new aliases   : {cart_added}")
        print(f"  mRNA new aliases    : {mrna_added}")
        if sample_cart:
            cat, tgt, adds = sample_cart
            print(f"\nSample CAR-T addition : {cat} (target={tgt!r})")
            for a in adds:
                print(f"    + {a}")
        if sample_mrna:
            cat, nm, adds = sample_mrna
            print(f"\nSample mRNA addition  : {cat} ({nm!r})")
            for a in adds:
                print(f"    + {a}")

        if not args.apply:
            print("\n--dry-run (no writes). Re-run with --apply to commit.")
            return 0

        if not updates:
            print("\nNothing to write.")
            return 0

        print(f"\nApplying in batches of {args.batch_size}...")
        with conn.cursor() as cur:
            for batch_start in range(0, len(updates), args.batch_size):
                batch = updates[batch_start : batch_start + args.batch_size]
                cur.executemany(
                    """
                    UPDATE product_catalog
                    SET aliases = %s, aliases_normalized = %s
                    WHERE id = %s
                    """,
                    [(Jsonb(a), Jsonb(n), rid) for rid, a, n in batch],
                )
                print(f"  {min(batch_start + args.batch_size, len(updates))}/{len(updates)}")
            conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM product_catalog
                WHERE jsonb_array_length(aliases) <> jsonb_array_length(aliases_normalized)
                """
            )
            mismatch = cur.fetchone()[0]
        print(f"\nPost-apply length mismatches: {mismatch} (must be 0)")
        if mismatch:
            print("ERROR: length mismatch after expand. Investigate.")
            return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
