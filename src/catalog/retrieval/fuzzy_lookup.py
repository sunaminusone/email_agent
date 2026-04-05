from __future__ import annotations

from typing import Any

from src.catalog.normalization import (
    DEFAULT_LIMIT,
    DEFAULT_SIMILARITY_THRESHOLD,
    clean_text,
    like_pattern,
    normalize_business_line_hint,
    normalize_query_text,
    select_search_term,
    token_regex,
)
from .shared import (
    BUSINESS_LINE_MATCH_SQL,
    PRODUCT_SELECT_SQL,
    dict_row,
    serialize_match,
)


def fuzzy_lookup(
    conn: Any,
    *,
    query: str,
    catalog_numbers: list[str],
    product_names: list[str],
    service_names: list[str],
    targets: list[str],
    applications: list[str],
    species: list[str],
    format_or_size: str = "",
    business_line_hint: str = "",
    top_k: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    search_basis = " ".join(product_names + service_names + targets).strip()
    normalized_query = normalize_query_text(search_basis or query)
    if not normalized_query:
        normalized_query = normalize_query_text(" ".join(catalog_numbers + product_names + service_names + targets))
    if not normalized_query:
        return []

    primary_token = select_search_term(
        query=query,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
    )
    like_value = like_pattern(primary_token)
    regex_value = token_regex(primary_token) if primary_token else r"$^"
    application_token = clean_text(applications[0]) if applications else ""
    species_token = clean_text(species[0]) if species else ""
    format_token = clean_text(format_or_size)
    application_like = like_pattern(application_token) if application_token else "%"
    species_like = like_pattern(species_token) if species_token else "%"
    format_like = like_pattern(format_token) if format_token else "%"
    business_filter_sql = ""

    normalized_business_line = normalize_business_line_hint(business_line_hint)
    if normalized_business_line:
        business_filter_sql = f"AND {BUSINESS_LINE_MATCH_SQL.format(field='p.business_line')}"

    sql = f"""
        {PRODUCT_SELECT_SQL},
            similarity(search_text, normalize_catalog_text(%s)) AS score,
            CASE
                WHEN p.catalog_no ILIKE %s THEN 40
                WHEN coalesce(p.name, '') ~* %s OR coalesce(p.display_name, '') ~* %s THEN 30
                WHEN coalesce(p.target_antigen, '') ~* %s THEN 25
                WHEN coalesce(p.name, '') ILIKE %s OR coalesce(p.display_name, '') ILIKE %s THEN 20
                WHEN similarity(p.search_text, normalize_catalog_text(%s)) >= %s THEN 10
                ELSE 1
            END
            + CASE
                WHEN %s <> '' AND coalesce(p.application_text, '') ILIKE %s THEN 4
                ELSE 0
            END
            + CASE
                WHEN %s <> '' AND coalesce(p.species_reactivity_text, '') ILIKE %s THEN 4
                ELSE 0
            END
            + CASE
                WHEN %s <> '' AND coalesce(p.format, '') ILIKE %s THEN 2
                ELSE 0
            END AS match_rank,
            'fuzzy' AS matched_field,
            %s AS matched_value
        FROM product_catalog p
        WHERE p.is_active = TRUE
          {business_filter_sql}
          AND (
              p.catalog_no ILIKE %s
              OR coalesce(p.name, '') ILIKE %s
              OR coalesce(p.display_name, '') ILIKE %s
              OR coalesce(p.target_antigen, '') ILIKE %s
              OR similarity(p.search_text, normalize_catalog_text(%s)) >= %s
          )
        ORDER BY match_rank DESC, score DESC, p.catalog_no NULLS LAST
        LIMIT %s
    """

    base_params: list[Any] = [
        normalized_query,
        like_value,
        regex_value,
        regex_value,
        regex_value,
        like_value,
        like_value,
        normalized_query,
        DEFAULT_SIMILARITY_THRESHOLD,
        application_token,
        application_like,
        species_token,
        species_like,
        format_token,
        format_like,
        primary_token,
    ]
    if normalized_business_line:
        base_params.append(normalized_business_line)
    base_params.extend([
        like_value,
        like_value,
        like_value,
        like_value,
        normalized_query,
        DEFAULT_SIMILARITY_THRESHOLD,
        top_k,
    ])

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, base_params)
        return [serialize_match(row) for row in cur.fetchall()]
