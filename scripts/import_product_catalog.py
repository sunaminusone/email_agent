#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None
    Jsonb = None


ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.objects.normalizers import clean_text as _clean_text
from src.objects.normalizers import normalize_object_alias as _normalize_object_alias
DEFAULT_FILES = {
    "antibody": ROOT / "data" / "processed" / "antibody_products.xlsx",
    "cart": ROOT / "data" / "processed" / "CAR_T_products.xlsx",
    "mrna": ROOT / "data" / "processed" / "mRNA_LNP_products.xlsx",
}

PRODUCT_COLUMNS = [
    "business_line",
    "record_type",
    "catalog_no",
    "name",
    "price",
    "currency",
    "lead_time_text",
    "aliases",
    "aliases_normalized",
    "applications",
    "species_reactivity",
    "target_antigen",
    "product_type",
    "format",
    "attributes",
    "raw_row",
    "source_file_path",
    "source_sheet",
    "source_row_number",
]

UPSERT_ASSIGNMENTS = [
    column for column in PRODUCT_COLUMNS if column not in {"catalog_no"}
]


def jsonb(value: Any) -> Any:
    if Jsonb is None:
        return value
    return Jsonb(value)


def normalize_alias_with_fallback(alias: object) -> str:
    """Mirror scripts/backfill_aliases_normalized.py::normalize_with_fallback.

    Single source of truth for the normalize step is normalize_object_alias.
    Fallback to lowered clean_text avoids '' polluting the GIN index;
    sentinel '__empty__' preserves length-equality with the source array
    when the alias was None/empty/pure-punct (data quality issue worth
    surfacing rather than silently dropping).
    """
    primary = _normalize_object_alias(alias)
    if primary:
        return primary
    fallback = _clean_text(alias).lower()
    if fallback:
        return fallback
    return "__empty__"


def assign_aliases(record: dict[str, Any], aliases_list: list[str]) -> None:
    """Set aliases + aliases_normalized atomically. ALL writers go through here.

    Length invariant required by chk_aliases_normalized_length CHECK on
    product_catalog: jsonb_array_length(aliases) == jsonb_array_length(aliases_normalized).
    """
    record["aliases"] = jsonb(aliases_list)
    record["aliases_normalized"] = jsonb(
        [normalize_alias_with_fallback(alias) for alias in aliases_list]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import product catalog data from Excel files into PostgreSQL."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection string. Falls back to DATABASE_URL / PG* env vars.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate product_catalog before import.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and map rows without writing to PostgreSQL.",
    )
    return parser.parse_args()


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def to_text(value: Any) -> str | None:
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def to_decimal(value: Any) -> Decimal | None:
    value = clean_value(value)
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def split_tokens(text: Any, separators: Iterable[str]) -> list[str]:
    value = to_text(text)
    if not value:
        return []
    parts = [value]
    for separator in separators:
        new_parts: list[str] = []
        for part in parts:
            new_parts.extend(part.split(separator))
        parts = new_parts
    tokens = [part.strip() for part in parts if part and part.strip()]
    return dedupe_tokens(tokens)


def dedupe_tokens(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = to_text(value)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(text)
    return deduped


def cleaned_row_dict(raw: pd.Series) -> dict[str, Any]:
    return {
        str(key).strip(): clean_value(value)
        for key, value in raw.to_dict().items()
    }


def base_record(
    *,
    business_line: str,
    record_type: str,
    catalog_no: Any,
    name: Any,
    source_file_path: Path,
    source_sheet: str,
    source_row_number: int,
) -> dict[str, Any]:
    return {
        "business_line": business_line,
        "record_type": record_type,
        "catalog_no": to_text(catalog_no),
        "name": to_text(name),
        "price": None,
        "currency": "USD",
        "lead_time_text": None,
        "aliases": jsonb([]),
        "aliases_normalized": jsonb([]),
        "applications": jsonb([]),
        "species_reactivity": jsonb([]),
        "target_antigen": None,
        "product_type": None,
        "format": None,
        "attributes": jsonb({}),
        "raw_row": jsonb({}),
        "source_file_path": str(source_file_path),
        "source_sheet": source_sheet,
        "source_row_number": source_row_number,
    }


def build_antibody_rows(excel_path: Path, sheet_name: str) -> list[dict[str, Any]]:
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    rows: list[dict[str, Any]] = []
    for idx, raw in df.iterrows():
        record = base_record(
            business_line="Antibody",
            record_type=sheet_name,
            catalog_no=raw.get("Catalog#"),
            name=raw.get("title"),
            source_file_path=excel_path,
            source_sheet=sheet_name,
            source_row_number=idx + 2,
        )
        if not record["catalog_no"] or not record["name"]:
            continue

        alias_text = raw.get("Also known as ")
        application_text = raw.get("Application") or raw.get("Applications")
        species_text = raw.get("Species Reactivity")
        raw_payload = cleaned_row_dict(raw)

        attributes = {
            "clone": to_text(raw.get("clone")),
            "isotype": to_text(raw.get("Isotype")),
            "ig_class": to_text(raw.get("Ig class")),
            "gene_id": to_text(raw.get("Gene ID")),
            "gene_accession": to_text(raw.get("Gene Accession")),
            "swissprot": to_text(raw.get("Swissprot")),
        }

        record["price"] = to_decimal(raw.get("cost"))
        record["lead_time_text"] = to_text(raw.get("Total time"))
        assign_aliases(
            record,
            dedupe_tokens(
                [record["catalog_no"], record["name"], *split_tokens(alias_text, [";", ","])]
            ),
        )
        record["applications"] = jsonb(split_tokens(application_text, [";", ","]))
        record["species_reactivity"] = jsonb(split_tokens(species_text, [",", ";"]))
        record["attributes"] = jsonb({k: v for k, v in attributes.items() if v is not None})
        record["raw_row"] = jsonb(raw_payload)
        rows.append(record)
    return rows


def build_cart_rows(excel_path: Path) -> list[dict[str, Any]]:
    df = pd.read_excel(excel_path, sheet_name="Sheet1")
    rows: list[dict[str, Any]] = []
    for idx, raw in df.iterrows():
        target = to_text(raw.get("target_antigen"))
        domain = to_text(raw.get("costimulatory_domain"))
        fallback_name = " ".join(part for part in [target, domain, "CAR-T"] if part)
        record = base_record(
            business_line="CAR-T/CAR-NK",
            record_type=to_text(raw.get("group_type")) or "cell_product",
            catalog_no=raw.get("catalog_no"),
            name=raw.get("name") if clean_value(raw.get("name")) else fallback_name,
            source_file_path=excel_path,
            source_sheet="Sheet1",
            source_row_number=idx + 2,
        )
        if not record["catalog_no"] or not record["name"]:
            continue

        construct = to_text(raw.get("construct"))
        group_name = to_text(raw.get("group_name"))
        raw_payload = cleaned_row_dict(raw)

        record["price"] = to_decimal(raw.get("price_usd"))
        record["lead_time_text"] = to_text(raw.get("total_time"))
        record["target_antigen"] = target
        assign_aliases(
            record,
            dedupe_tokens(
                [
                    record["catalog_no"],
                    record["name"],
                    f"{target} CAR-T" if target else None,
                    f"{target} {domain} CAR-T" if target and domain else None,
                    construct,
                    group_name,
                ]
            ),
        )
        record["attributes"] = jsonb(
            {
                k: v
                for k, v in {
                    "costimulatory_domain": domain,
                    "construct": construct,
                    "unit": to_text(raw.get("unit")),
                    "cell_number": to_text(raw.get("cell_number")),
                    "marker": to_text(raw.get("marker")),
                    "group_name": group_name,
                    "group_type": to_text(raw.get("group_type")),
                    "group_subtype": to_text(raw.get("group_subtype")),
                    "group_summary": to_text(raw.get("group_summary")),
                }.items()
                if v is not None
            }
        )
        record["raw_row"] = jsonb(raw_payload)
        rows.append(record)
    return rows


def build_mrna_rows(excel_path: Path) -> list[dict[str, Any]]:
    df = pd.read_excel(excel_path, sheet_name="Sheet1")
    rows: list[dict[str, Any]] = []
    for idx, raw in df.iterrows():
        record = base_record(
            business_line="mRNA-LNP",
            record_type="product",
            catalog_no=raw.get("catalog_no"),
            name=raw.get("name"),
            source_file_path=excel_path,
            source_sheet="Sheet1",
            source_row_number=idx + 2,
        )
        if not record["catalog_no"] or not record["name"]:
            continue

        product_type = to_text(raw.get("type"))
        format_value = to_text(raw.get("format"))
        raw_payload = cleaned_row_dict(raw)

        record["price"] = to_decimal(raw.get("price_usd"))
        record["product_type"] = product_type
        record["format"] = format_value
        assign_aliases(
            record,
            dedupe_tokens([record["catalog_no"], record["name"], product_type, format_value]),
        )
        record["raw_row"] = jsonb(raw_payload)
        rows.append(record)
    return rows


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


def upsert_products(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    placeholders = ", ".join(["%s"] * len(PRODUCT_COLUMNS))
    columns_sql = ", ".join(PRODUCT_COLUMNS)
    update_sql = ", ".join(f"{column} = EXCLUDED.{column}" for column in UPSERT_ASSIGNMENTS)
    sql = f"""
        INSERT INTO product_catalog ({columns_sql})
        VALUES ({placeholders})
        ON CONFLICT (catalog_no)
        DO UPDATE SET {update_sql}, updated_at = CURRENT_TIMESTAMP
    """

    values = [tuple(row.get(column) for column in PRODUCT_COLUMNS) for row in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, values)


def collect_rows() -> list[dict[str, Any]]:
    antibody_path = DEFAULT_FILES["antibody"]
    cart_path = DEFAULT_FILES["cart"]
    mrna_path = DEFAULT_FILES["mrna"]

    rows: list[dict[str, Any]] = []
    for sheet_name in ["Monoclonal Antibody", "Polyclonal Antibody"]:
        rows.extend(build_antibody_rows(antibody_path, sheet_name))
    rows.extend(build_cart_rows(cart_path))
    rows.extend(build_mrna_rows(mrna_path))
    return rows


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()

    all_rows = collect_rows()
    if args.dry_run:
        print(f"Dry run complete. Prepared {len(all_rows)} product rows for import.")
        return

    if psycopg is None:
        raise RuntimeError(
            "psycopg is not installed. Run `pip install -r requirements.txt` first."
        )

    connection_string = get_connection_string(args.database_url)
    with psycopg.connect(connection_string) as conn:
        if args.truncate:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE product_catalog RESTART IDENTITY")
        upsert_products(conn, all_rows)
        conn.commit()
    print(f"Imported {len(all_rows)} rows into product_catalog.")


if __name__ == "__main__":
    main()
