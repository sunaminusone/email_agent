#!/usr/bin/env python3
"""Populate catalog_alias_map from the in-memory product registry.

The registry expands target-antigen / family-descriptor aliases beyond what is
stored in ``product_catalog.also_known_as`` / ``product_catalog.aliases``.
Running this script mirrors those expansions into PostgreSQL so the
``catalog_alias_map`` table — used by ``alias_lookup`` — agrees with the
entity-extraction layer.

Products that have no registry entry (e.g. service SKUs, ad-hoc rows) still
get their ``also_known_as`` / ``aliases`` indexed via the legacy path.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None
    dict_row = None

from src.objects.normalizers import normalize_object_alias

WHITESPACE_RE = re.compile(r"\s+")
SPLIT_RE = re.compile(r"\s*[;,]\s*")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate catalog_alias_map from the product registry."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection string. Falls back to DATABASE_URL / PG* env vars.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate catalog_alias_map before reloading aliases.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview alias rows without writing to PostgreSQL.",
    )
    return parser.parse_args()


def build_connection_string(explicit_url: str | None) -> str:
    if explicit_url:
        return explicit_url

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    dbname = os.getenv("PGDATABASE", "promab")

    auth = user
    if password:
        auth = f"{user}:{password}"
    return f"postgresql://{auth}@{host}:{port}/{dbname}"


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return WHITESPACE_RE.sub(" ", str(value).strip())


def normalize_alias(value: object) -> str:
    return normalize_object_alias(clean_text(value))


def split_alias_text(value: object) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = [part.strip() for part in SPLIT_RE.split(text) if part and part.strip()]
    seen: set[str] = set()
    aliases: list[str] = []
    for part in parts:
        normalized = normalize_alias(part)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(part)
    return aliases


def _legacy_alias_rows(row: dict) -> Iterable[tuple[str, str]]:
    seen: set[str] = set()
    for alias in split_alias_text(row.get("also_known_as")):
        normalized = normalize_alias(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        yield alias, "also_known_as"

    aliases_json = row.get("aliases") or []
    if isinstance(aliases_json, list):
        for alias in aliases_json:
            cleaned = clean_text(alias)
            normalized = normalize_alias(cleaned)
            if not cleaned or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            yield cleaned, "aliases"


def main() -> int:
    args = parse_args()
    if psycopg is None:
        raise SystemExit("psycopg is not installed. Please install psycopg[binary] first.")

    from src.objects.registries.product_registry import iter_product_alias_records

    registry_rows = iter_product_alias_records()
    registry_by_catalog: dict[str, list[tuple[str, str, str]]] = {}
    for catalog_no, alias, normalized, alias_kind in registry_rows:
        key = catalog_no.strip().upper()
        if not key:
            continue
        registry_by_catalog.setdefault(key, []).append((alias, normalized, alias_kind))

    connection_string = build_connection_string(args.database_url)

    select_sql = """
        SELECT id, catalog_no, also_known_as, aliases
        FROM product_catalog
        WHERE is_active = TRUE
        ORDER BY catalog_no NULLS LAST, id
    """

    insert_sql = """
        INSERT INTO catalog_alias_map (
            product_id,
            alias,
            alias_normalized,
            source_field
        )
        VALUES (%s, %s, %s, %s)
    """

    with psycopg.connect(connection_string) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(select_sql)
            rows = cur.fetchall()

        alias_rows: list[tuple[str, str, str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        matched_products = 0

        for row in rows:
            product_id = str(row["id"])
            catalog_key = clean_text(row.get("catalog_no")).upper()
            registry_matches = registry_by_catalog.get(catalog_key, [])
            if registry_matches:
                matched_products += 1
                for alias, normalized, alias_kind in registry_matches:
                    pair = (product_id, normalized)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    source_field = alias_kind or "registry"
                    alias_rows.append((product_id, alias, normalized, source_field))

            for alias, source_field in _legacy_alias_rows(row):
                normalized = normalize_alias(alias)
                pair = (product_id, normalized)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                alias_rows.append((product_id, alias, normalized, source_field))

        if args.dry_run:
            print(
                f"Prepared {len(alias_rows)} alias rows from {len(rows)} products; "
                f"{matched_products} products resolved to registry entries."
            )
            for sample in alias_rows[:20]:
                print(sample)
            return 0

        with conn.cursor() as cur:
            if args.truncate:
                cur.execute("TRUNCATE TABLE catalog_alias_map")
            else:
                cur.execute("DELETE FROM catalog_alias_map")
            if alias_rows:
                cur.executemany(insert_sql, alias_rows)
        conn.commit()

    print(
        f"Inserted {len(alias_rows)} alias rows into catalog_alias_map "
        f"({matched_products}/{len(rows)} products matched to registry)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
