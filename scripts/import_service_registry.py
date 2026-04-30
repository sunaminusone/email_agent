#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None
    Jsonb = None


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.objects.registries.service_registry import FilesServiceRegistrySource

SERVICE_COLUMNS = [
    "canonical_name",
    "business_line",
    "aliases",
    "service_line",
    "subcategory",
    "page_title",
    "document_summary",
    "source_url",
    "source_path",
    "source_file",
]


def jsonb(value: Any) -> Any:
    if Jsonb is None:
        return value
    return Jsonb(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import service registry data from rag-ready service pages into PostgreSQL."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection string. Falls back to DATABASE_URL / PG* env vars.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate service_catalog before import.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to PostgreSQL. Without this flag, runs in dry-run mode "
             "(parses + reports row count, no DB writes). Mirrors the "
             "scripts/backfill_aliases_normalized.py convention.",
    )
    return parser.parse_args()


def get_connection_string(explicit_value: str | None) -> str:
    if explicit_value:
        return explicit_value
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    host = os.getenv("PGHOST")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    dbname = os.getenv("PGDATABASE")
    if not all([host, user, password, dbname]):
        raise ValueError(
            "Missing PostgreSQL config. Set DATABASE_URL or PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE."
        )
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def collect_rows() -> list[dict[str, Any]]:
    source = FilesServiceRegistrySource()
    rows: list[dict[str, Any]] = []
    for entry in source.load_entries():
        rows.append(
            {
                "canonical_name": entry.canonical_name,
                "business_line": entry.business_line,
                "aliases": jsonb(list(entry.aliases)),
                "service_line": entry.service_line,
                "subcategory": entry.subcategory,
                "page_title": entry.page_title,
                "document_summary": entry.document_summary,
                "source_url": entry.source_url,
                "source_path": entry.source_path,
                "source_file": entry.source_file,
            }
        )
    return rows


def upsert_services(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    placeholders = ", ".join(["%s"] * len(SERVICE_COLUMNS))
    columns_sql = ", ".join(SERVICE_COLUMNS)
    update_sql = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in SERVICE_COLUMNS if column != "canonical_name"
    )
    sql = f"""
        INSERT INTO service_catalog ({columns_sql})
        VALUES ({placeholders})
        ON CONFLICT (canonical_name)
        DO UPDATE SET {update_sql}, updated_at = CURRENT_TIMESTAMP
    """
    values = [tuple(row.get(column) for column in SERVICE_COLUMNS) for row in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, values)


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    rows = collect_rows()
    if not args.apply:
        print(f"Dry run complete. Prepared {len(rows)} service rows for import.")
        print("Re-run with --apply to commit.")
        return

    if psycopg is None:
        raise RuntimeError(
            "psycopg is not installed. Run `pip install -r requirements.txt` first."
        )

    connection_string = get_connection_string(args.database_url)
    with psycopg.connect(connection_string) as conn:
        if args.truncate:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE service_catalog RESTART IDENTITY")
        upsert_services(conn, rows)
        conn.commit()
    print(f"Imported {len(rows)} rows into service_catalog.")


if __name__ == "__main__":
    main()
