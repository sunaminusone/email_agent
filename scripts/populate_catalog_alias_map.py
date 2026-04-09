#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from typing import Iterable

try:
    import psycopg
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None


WHITESPACE_RE = re.compile(r"\s+")
SPLIT_RE = re.compile(r"\s*[;,]\s*")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate catalog_alias_map from product_catalog aliases."
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
    return clean_text(value).lower()


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


def collect_alias_candidates(row: dict) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for alias in split_alias_text(row.get("also_known_as")):
        normalized = normalize_alias(alias)
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(alias)

    aliases_json = row.get("aliases") or []
    if isinstance(aliases_json, list):
        for alias in aliases_json:
            cleaned = clean_text(alias)
            normalized = normalize_alias(cleaned)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(cleaned)

    return candidates


def main() -> int:
    args = parse_args()
    if psycopg is None:
        raise SystemExit("psycopg is not installed. Please install psycopg[binary] first.")

    connection_string = build_connection_string(args.database_url)

    select_sql = """
        SELECT id, catalog_no, name, also_known_as, aliases
        FROM product_catalog
        WHERE is_active = TRUE
          AND (
                coalesce(also_known_as, '') <> ''
                OR jsonb_array_length(coalesce(aliases, '[]'::jsonb)) > 0
          )
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
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(select_sql)
            rows = cur.fetchall()

        alias_rows: list[tuple[str, str, str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()

        for row in rows:
            product_id = str(row["id"])
            for alias in collect_alias_candidates(row):
                normalized = normalize_alias(alias)
                pair = (product_id, normalized)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                alias_rows.append((product_id, alias, normalized, "also_known_as"))

        if args.dry_run:
            print(f"Prepared {len(alias_rows)} alias rows from {len(rows)} products.")
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

    print(f"Inserted {len(alias_rows)} alias rows into catalog_alias_map.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
