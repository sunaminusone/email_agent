from __future__ import annotations

from typing import Any

from src.catalog.normalization import DEFAULT_LIMIT, normalize_business_line_hint
from .shared import (
    BUSINESS_LINE_MATCH_SQL,
    PRODUCT_SELECT_SQL,
    dict_row,
    serialize_match,
)


def catalog_number_lookup(
    conn: Any,
    *,
    catalog_numbers: list[str],
    business_line_hint: str = "",
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    if not catalog_numbers:
        return []

    conditions = ["catalog_no = ANY(%s)"]
    params: list[Any] = [catalog_numbers]
    normalized_business_line = normalize_business_line_hint(business_line_hint)
    if normalized_business_line:
        conditions.append(BUSINESS_LINE_MATCH_SQL.format(field="business_line"))
        params.append(normalized_business_line)
    params.append(limit)

    sql = f"""
        {PRODUCT_SELECT_SQL},
            1.0 AS score,
            200 AS match_rank,
            'catalog_no' AS matched_field,
            catalog_no AS matched_value
        FROM product_catalog p
        WHERE {" AND ".join(conditions)}
        ORDER BY p.catalog_no
        LIMIT %s
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [serialize_match(row) for row in cur.fetchall()]
