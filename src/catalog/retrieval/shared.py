from __future__ import annotations

import os
from typing import Any

from src.catalog.normalization import (
    clean_text,
    decimal_to_number,
    normalize_query_text,
    split_query_terms,
)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None


PRODUCT_SELECT_SQL = """
    SELECT
        p.id,
        p.catalog_no,
        p.name,
        p.name AS display_name,
        p.business_line,
        p.record_type,
        p.price,
        p.price::text AS price_text,
        p.lead_time_text,
        p.currency,
        array_to_string(ARRAY(SELECT jsonb_array_elements_text(p.aliases)), ', ') AS also_known_as,
        p.target_antigen,
        array_to_string(ARRAY(SELECT jsonb_array_elements_text(p.applications)), ', ') AS application_text,
        array_to_string(ARRAY(SELECT jsonb_array_elements_text(p.species_reactivity)), ', ') AS species_reactivity_text,
        p.attributes->>'construct' AS construct,
        p.product_type,
        p.format,
        p.attributes->>'unit' AS unit
"""

BUSINESS_LINE_MATCH_SQL = "POSITION(LOWER(REPLACE(%s, '-', '_')) IN LOWER(REPLACE({field}, '-', '_'))) > 0"


def build_connection_string() -> str:
    from src.common.pg_runtime import with_runtime_timeouts

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return with_runtime_timeouts(database_url)

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    dbname = os.getenv("PGDATABASE", "promab")

    auth = user
    if password:
        auth = f"{user}:{password}"
    return with_runtime_timeouts(f"postgresql://{auth}@{host}:{port}/{dbname}")


def serialize_match(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id", "")),
        "catalog_no": row.get("catalog_no"),
        "name": row.get("name"),
        "display_name": row.get("display_name"),
        "business_line": row.get("business_line"),
        "record_type": row.get("record_type"),
        "price": decimal_to_number(row.get("price")),
        "price_text": row.get("price_text"),
        "lead_time_text": row.get("lead_time_text"),
        "currency": row.get("currency"),
        "also_known_as": row.get("also_known_as"),
        "target_antigen": row.get("target_antigen"),
        "application_text": row.get("application_text"),
        "species_reactivity_text": row.get("species_reactivity_text"),
        "construct": row.get("construct"),
        "product_type": row.get("product_type"),
        "format": row.get("format"),
        "unit": row.get("unit"),
        "score": round(float(row.get("score") or 0.0), 4),
        "match_rank": int(row.get("match_rank") or 0),
        "matched_field": row.get("matched_field"),
        "matched_value": row.get("matched_value"),
    }


def candidate_aliases(
    *,
    query: str,
    product_names: list[str],
    service_names: list[str],
    targets: list[str],
) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    raw_values = [*product_names, *service_names, *targets]
    seed_values = raw_values or [query]

    for value in seed_values:
        cleaned = normalize_query_text(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            candidates.append(cleaned)

    from src.catalog.normalization import LOW_SIGNAL_TOKENS

    if not raw_values:
        for token in split_query_terms(query):
            if token in LOW_SIGNAL_TOKENS or token in seen:
                continue
            seen.add(token)
            candidates.append(token)
    return candidates


__all__ = [
    "BUSINESS_LINE_MATCH_SQL",
    "PRODUCT_SELECT_SQL",
    "build_connection_string",
    "serialize_match",
    "candidate_aliases",
    "psycopg",
    "dict_row",
]
