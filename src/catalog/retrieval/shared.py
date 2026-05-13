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
        NULL::text AS product_type,
        p.size AS format,
        -- Antibody-facet columns (NULL on non-antibody rows via LEFT JOIN).
        a.host,
        a.isotype,
        a.clone,
        a.molecular_weight,
        a.gene_id,
        a.sequence,
        a.elisa_dilution,
        a.wb_dilution,
        a.fcm_dilution,
        a.ihc_dilution,
        a.icc_dilution,
        a.immunogen,
        a.references_text,
        -- CAR-T-facet columns (NULL on non-CAR-T rows).
        c.construct,
        c.costimulatory_domain,
        c.group_name,
        c.group_type,
        c.group_subtype,
        c.group_summary,
        c.cell_number,
        c.marker,
        c.unit,
        -- mRNA-LNP-facet columns (NULL on non-LNP rows). `lnp_` prefix on the
        -- two names that would collide with parent (record_type) or with the
        -- existing applications array (application_text).
        l.type AS lnp_type,
        l.application AS lnp_application,
        l.application_handling,
        l.cell_type_tested,
        l.data_sheet_url,
        -- Common provenance fields exist on all three child tables. COALESCE
        -- across the three: each row only has data on its own facet, so the
        -- non-NULL value wins.
        COALESCE(a.formulation, c.formulation, l.formulation) AS formulation,
        COALESCE(a.shipping,    c.shipping,    l.shipping)    AS shipping,
        COALESCE(a.storage,     c.storage,     l.storage)     AS storage,
        COALESCE(a.description, c.description, l.description) AS description
"""

# Shared FROM clause: parent table left-joined to all three CTI facets so
# business-line-specific fields are exposed in PRODUCT_SELECT_SQL without
# callers having to know the schema split. A row only ever has data on the
# child for its own business line; the other JOINs return NULL columns.
PRODUCT_FROM_SQL = """
    FROM product_catalog p
    LEFT JOIN antibody_product_catalog a ON a.product_id = p.id
    LEFT JOIN cart_product_catalog     c ON c.product_id = p.id
    LEFT JOIN lnp_product_catalog      l ON l.product_id = p.id
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
        "product_type": row.get("product_type"),
        "format": row.get("format"),
        # Antibody facet (None on non-antibody rows via LEFT JOIN).
        "host": row.get("host"),
        "isotype": row.get("isotype"),
        "clone": row.get("clone"),
        "molecular_weight": row.get("molecular_weight"),
        "gene_id": row.get("gene_id"),
        "sequence": row.get("sequence"),
        "elisa_dilution": row.get("elisa_dilution"),
        "wb_dilution": row.get("wb_dilution"),
        "fcm_dilution": row.get("fcm_dilution"),
        "ihc_dilution": row.get("ihc_dilution"),
        "icc_dilution": row.get("icc_dilution"),
        "immunogen": row.get("immunogen"),
        "references_text": row.get("references_text"),
        # CAR-T facet (None on non-CAR-T rows).
        "construct": row.get("construct"),
        "costimulatory_domain": row.get("costimulatory_domain"),
        "group_name": row.get("group_name"),
        "group_type": row.get("group_type"),
        "group_subtype": row.get("group_subtype"),
        "group_summary": row.get("group_summary"),
        "cell_number": row.get("cell_number"),
        "marker": row.get("marker"),
        "unit": row.get("unit"),
        # mRNA-LNP facet (None on non-LNP rows).
        "lnp_type": row.get("lnp_type"),
        "lnp_application": row.get("lnp_application"),
        "application_handling": row.get("application_handling"),
        "cell_type_tested": row.get("cell_type_tested"),
        "data_sheet_url": row.get("data_sheet_url"),
        # Common provenance (COALESCEd across the three facets).
        "formulation": row.get("formulation"),
        "storage": row.get("storage"),
        "shipping": row.get("shipping"),
        "description": row.get("description"),
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

    # Also emit individual high-signal tokens from the seed values so
    # tier-2 alias matching can hit token-level gene symbols like
    # "tp53" / "cd19" / "il6". Without this, a query such as
    # "Mouse Monoclonal Antibody to TP53" only ever produces the
    # whole-phrase candidate, which never exact-matches; the one product
    # whose aliases include "tp53" (#20338) drops to tier-3 fuzzy and
    # ranks behind false friends like Rabbit anti-TP53 / TP53BP1 because
    # its name contains "p53" not "tp53".
    # Restrict to digit-bearing tokens so we capture gene symbols /
    # specific identifiers but don't flood tier 2 with generic words
    # ("mouse", "monoclonal") that would over-match catalog aliases.
    token_source_values = raw_values or [query]
    for value in token_source_values:
        for token in split_query_terms(value):
            if token in seen or token in LOW_SIGNAL_TOKENS:
                continue
            if not any(ch.isdigit() for ch in token):
                continue
            seen.add(token)
            candidates.append(token)
    return candidates


__all__ = [
    "BUSINESS_LINE_MATCH_SQL",
    "PRODUCT_SELECT_SQL",
    "PRODUCT_FROM_SQL",
    "build_connection_string",
    "serialize_match",
    "candidate_aliases",
    "psycopg",
    "dict_row",
]
