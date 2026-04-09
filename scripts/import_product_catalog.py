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
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None
    dict_row = None
    Jsonb = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = {
    "antibody": ROOT / "data" / "processed" / "antibody_products.xlsx",
    "cart": ROOT / "data" / "processed" / "CAR_T_products.xlsx",
    "mrna": ROOT / "data" / "processed" / "mRNA_LNP_products.xlsx",
    "services": ROOT / "data" / "processed" / "other_custom_services.xlsx",
}

PRODUCT_COLUMNS = [
    "source_id",
    "source_type",
    "source_name",
    "source_file_path",
    "source_sheet",
    "source_row_number",
    "business_line",
    "record_type",
    "catalog_no",
    "name",
    "display_name",
    "description",
    "antibody_type",
    "clone_name",
    "isotype",
    "ig_class",
    "gene_id",
    "gene_accession",
    "swissprot",
    "also_known_as",
    "application_text",
    "species_reactivity_text",
    "target_antigen",
    "costimulatory_domain",
    "construct",
    "unit",
    "cell_number",
    "marker",
    "group_name",
    "group_type",
    "group_subtype",
    "group_summary",
    "product_type",
    "format",
    "currency",
    "price",
    "price_text",
    "lead_time_text",
    "aliases",
    "keywords",
    "applications",
    "species_reactivity",
    "raw_row",
    "raw_metadata",
]

UPSERT_ASSIGNMENTS = [
    column for column in PRODUCT_COLUMNS
    if column not in {"source_file_path", "source_sheet", "source_row_number"}
]


def jsonb(value: Any) -> Any:
    if Jsonb is None:
        return value
    return Jsonb(value)


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
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(token)
    return deduped


def build_common_record(
    *,
    source_id: str,
    source_name: str,
    source_file_path: Path,
    source_sheet: str,
    source_row_number: int,
    business_line: str,
    record_type: str,
    catalog_no: Any,
    name: Any,
) -> dict[str, Any]:
    name_text = to_text(name)
    catalog_text = to_text(catalog_no)
    return {
        "source_id": source_id,
        "source_type": "excel",
        "source_name": source_name,
        "source_file_path": str(source_file_path),
        "source_sheet": source_sheet,
        "source_row_number": source_row_number,
        "business_line": business_line,
        "record_type": record_type,
        "catalog_no": catalog_text,
        "name": name_text,
        "display_name": name_text or catalog_text,
        "description": None,
        "antibody_type": None,
        "clone_name": None,
        "isotype": None,
        "ig_class": None,
        "gene_id": None,
        "gene_accession": None,
        "swissprot": None,
        "also_known_as": None,
        "application_text": None,
        "species_reactivity_text": None,
        "target_antigen": None,
        "costimulatory_domain": None,
        "construct": None,
        "unit": None,
        "cell_number": None,
        "marker": None,
        "group_name": None,
        "group_type": None,
        "group_subtype": None,
        "group_summary": None,
        "product_type": None,
        "format": None,
        "currency": "USD",
        "price": None,
        "price_text": None,
        "lead_time_text": None,
        "aliases": jsonb([]),
        "keywords": jsonb([]),
        "applications": jsonb([]),
        "species_reactivity": jsonb([]),
        "raw_row": jsonb({}),
        "raw_metadata": jsonb({}),
    }


def build_antibody_rows(
    excel_path: Path,
    sheet_name: str,
    source_id: str,
    source_name: str,
) -> list[dict[str, Any]]:
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    rows: list[dict[str, Any]] = []
    for idx, raw in df.iterrows():
        record_type = sheet_name
        catalog_no = raw.get("Catalog#")
        record = build_common_record(
            source_id=source_id,
            source_name=source_name,
            source_file_path=excel_path,
            source_sheet=sheet_name,
            source_row_number=idx + 2,
            business_line="Antibody",
            record_type=record_type,
            catalog_no=catalog_no,
            name=raw.get("title"),
        )
        record["antibody_type"] = sheet_name
        record["clone_name"] = to_text(raw.get("clone"))
        record["isotype"] = to_text(raw.get("Isotype"))
        record["ig_class"] = to_text(raw.get("Ig class"))
        record["gene_id"] = to_text(raw.get("Gene ID"))
        record["gene_accession"] = to_text(raw.get("Gene Accession"))
        record["swissprot"] = to_text(raw.get("Swissprot"))
        record["also_known_as"] = to_text(raw.get("Also known as "))
        record["application_text"] = to_text(
            raw.get("Application") or raw.get("Applications")
        )
        record["species_reactivity_text"] = to_text(raw.get("Species Reactivity"))
        record["price"] = to_decimal(raw.get("cost"))
        record["price_text"] = to_text(raw.get("cost"))
        record["lead_time_text"] = to_text(raw.get("Total time"))
        record["aliases"] = jsonb(split_tokens(record["also_known_as"], [";", ","]))
        record["applications"] = jsonb(
            split_tokens(record["application_text"], [";", ","])
        )
        record["species_reactivity"] = jsonb(
            split_tokens(record["species_reactivity_text"], [",", ";"])
        )
        record["keywords"] = jsonb(
            [
                token
                for token in [
                    record["business_line"],
                    record["record_type"],
                    record["antibody_type"],
                    record["catalog_no"],
                ]
                if token
            ]
        )
        record["raw_row"] = jsonb(
            {str(key).strip(): clean_value(value) for key, value in raw.to_dict().items()}
        )
        rows.append(record)
    return rows


def build_cart_rows(
    excel_path: Path,
    source_id: str,
    source_name: str,
) -> list[dict[str, Any]]:
    df = pd.read_excel(excel_path, sheet_name="Sheet1")
    rows: list[dict[str, Any]] = []
    for idx, raw in df.iterrows():
        target = to_text(raw.get("target_antigen"))
        domain = to_text(raw.get("costimulatory_domain"))
        generated_name = " ".join(part for part in [target, domain, "CAR-T"] if part)
        record = build_common_record(
            source_id=source_id,
            source_name=source_name,
            source_file_path=excel_path,
            source_sheet="Sheet1",
            source_row_number=idx + 2,
            business_line="CAR-T/CAR-NK",
            record_type=to_text(raw.get("group_type")) or "cell_product",
            catalog_no=raw.get("catalog_no"),
            name=raw.get("name") if clean_value(raw.get("name")) else generated_name,
        )
        record["target_antigen"] = target
        record["costimulatory_domain"] = domain
        record["construct"] = to_text(raw.get("construct"))
        record["unit"] = to_text(raw.get("unit"))
        record["cell_number"] = to_text(raw.get("cell_number"))
        record["marker"] = to_text(raw.get("marker"))
        record["group_name"] = to_text(raw.get("group_name"))
        record["group_type"] = to_text(raw.get("group_type"))
        record["group_subtype"] = to_text(raw.get("group_subtype"))
        record["group_summary"] = to_text(raw.get("group_summary"))
        record["price"] = to_decimal(raw.get("price_usd"))
        record["price_text"] = to_text(raw.get("price_usd"))
        record["lead_time_text"] = to_text(raw.get("total_time"))
        record["keywords"] = jsonb(
            [
                token
                for token in [
                    record["business_line"],
                    record["record_type"],
                    record["group_name"],
                    record["target_antigen"],
                    record["costimulatory_domain"],
                    record["catalog_no"],
                ]
                if token
            ]
        )
        record["raw_row"] = jsonb(
            {str(key).strip(): clean_value(value) for key, value in raw.to_dict().items()}
        )
        rows.append(record)
    return rows


def build_mrna_rows(
    excel_path: Path,
    source_id: str,
    source_name: str,
) -> list[dict[str, Any]]:
    df = pd.read_excel(excel_path, sheet_name="Sheet1")
    rows: list[dict[str, Any]] = []
    for idx, raw in df.iterrows():
        record = build_common_record(
            source_id=source_id,
            source_name=source_name,
            source_file_path=excel_path,
            source_sheet="Sheet1",
            source_row_number=idx + 2,
            business_line="mRNA-LNP",
            record_type="product",
            catalog_no=raw.get("catalog_no"),
            name=raw.get("name"),
        )
        record["product_type"] = to_text(raw.get("type"))
        record["format"] = to_text(raw.get("format"))
        record["price"] = to_decimal(raw.get("price_usd"))
        record["price_text"] = to_text(raw.get("price_usd"))
        record["keywords"] = jsonb(
            [
                token
                for token in [
                    record["business_line"],
                    record["record_type"],
                    record["product_type"],
                    record["catalog_no"],
                ]
                if token
            ]
        )
        record["raw_row"] = jsonb(
            {str(key).strip(): clean_value(value) for key, value in raw.to_dict().items()}
        )
        rows.append(record)
    return rows


def build_service_rows(
    excel_path: Path,
    source_id: str,
    source_name: str,
) -> list[dict[str, Any]]:
    df = pd.read_excel(excel_path, sheet_name="Sheet 1", header=2)
    df = df.dropna(how="all")
    rows: list[dict[str, Any]] = []
    for idx, raw in df.iterrows():
        total_cost = raw.get("total_cost")
        record = build_common_record(
            source_id=source_id,
            source_name=source_name,
            source_file_path=excel_path,
            source_sheet="Sheet 1",
            source_row_number=idx + 4,
            business_line=to_text(raw.get("business_line")) or "Other service",
            record_type="custom_service",
            catalog_no=raw.get("catalog_no"),
            name=raw.get("name"),
        )
        record["unit"] = to_text(raw.get("Unit"))
        record["price"] = to_decimal(total_cost)
        record["price_text"] = to_text(total_cost)
        record["lead_time_text"] = to_text(raw.get("Time"))
        record["keywords"] = jsonb(
            [
                token
                for token in [
                    record["business_line"],
                    record["record_type"],
                    record["catalog_no"],
                ]
                if token
            ]
        )
        record["raw_row"] = jsonb(
            {str(key).strip(): clean_value(value) for key, value in raw.to_dict().items()}
        )
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


def insert_source(
    conn: psycopg.Connection[Any],
    *,
    source_name: str,
    file_path: Path,
    note: str,
) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO catalog_source (source_name, source_type, file_path, note)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (source_name, "excel", str(file_path), note),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Failed to create catalog_source row for {source_name}")
    return str(row["id"])


def upsert_products(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    placeholders = ", ".join(["%s"] * len(PRODUCT_COLUMNS))
    columns_sql = ", ".join(PRODUCT_COLUMNS)
    update_sql = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in UPSERT_ASSIGNMENTS
    )
    sql = f"""
        INSERT INTO product_catalog ({columns_sql})
        VALUES ({placeholders})
        ON CONFLICT (source_file_path, source_sheet, source_row_number)
        DO UPDATE SET {update_sql}, updated_at = CURRENT_TIMESTAMP
    """

    values = [
        tuple(row.get(column) for column in PRODUCT_COLUMNS)
        for row in rows
    ]

    with conn.cursor() as cur:
        cur.executemany(sql, values)


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()

    antibody_path = DEFAULT_FILES["antibody"]
    cart_path = DEFAULT_FILES["cart"]
    mrna_path = DEFAULT_FILES["mrna"]
    services_path = DEFAULT_FILES["services"]
    all_rows: list[dict[str, Any]] = []

    if args.dry_run:
        for sheet_name in ["Monoclonal Antibody", "Polyclonal Antibody"]:
            source_name = f"{antibody_path.name}:{sheet_name}"
            all_rows.extend(
                build_antibody_rows(antibody_path, sheet_name, "dry-run", source_name)
            )

        all_rows.extend(
            build_cart_rows(cart_path, "dry-run", f"{cart_path.name}:Sheet1")
        )
        all_rows.extend(
            build_mrna_rows(mrna_path, "dry-run", f"{mrna_path.name}:Sheet1")
        )
        all_rows.extend(
            build_service_rows(services_path, "dry-run", f"{services_path.name}:Sheet 1")
        )
        print(f"Dry run complete. Prepared {len(all_rows)} rows for import.")
        return

    if psycopg is None:
        raise RuntimeError(
            "psycopg is not installed. Run `pip install -r requirements.txt` first."
        )

    connection_string = get_connection_string(args.database_url)

    with psycopg.connect(connection_string) as conn:
        if args.truncate:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE product_catalog RESTART IDENTITY CASCADE")

        for sheet_name in ["Monoclonal Antibody", "Polyclonal Antibody"]:
            source_name = f"{antibody_path.name}:{sheet_name}"
            source_id = insert_source(
                conn,
                source_name=source_name,
                file_path=antibody_path,
                note=f"Imported from antibody_products.xlsx / {sheet_name}",
            )
            all_rows.extend(
                build_antibody_rows(antibody_path, sheet_name, source_id, source_name)
            )

        cart_source_name = f"{cart_path.name}:Sheet1"
        cart_source_id = insert_source(
            conn,
            source_name=cart_source_name,
            file_path=cart_path,
            note="Imported from CAR_T_products.xlsx / Sheet1",
        )
        all_rows.extend(build_cart_rows(cart_path, cart_source_id, cart_source_name))

        mrna_source_name = f"{mrna_path.name}:Sheet1"
        mrna_source_id = insert_source(
            conn,
            source_name=mrna_source_name,
            file_path=mrna_path,
            note="Imported from mRNA_LNP_products.xlsx / Sheet1",
        )
        all_rows.extend(build_mrna_rows(mrna_path, mrna_source_id, mrna_source_name))

        services_source_name = f"{services_path.name}:Sheet 1"
        services_source_id = insert_source(
            conn,
            source_name=services_source_name,
            file_path=services_path,
            note="Imported from other_custom_services.xlsx / Sheet 1",
        )
        all_rows.extend(
            build_service_rows(services_path, services_source_id, services_source_name)
        )

        upsert_products(conn, all_rows)
        conn.commit()
        print(f"Imported {len(all_rows)} rows into product_catalog.")


if __name__ == "__main__":
    main()
