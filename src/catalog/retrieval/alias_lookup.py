from __future__ import annotations

from typing import Any

from src.catalog.normalization import DEFAULT_LIMIT, normalize_business_line_hint, token_regex
from src.objects.normalizers import normalize_object_alias
from .shared import (
    BUSINESS_LINE_MATCH_SQL,
    PRODUCT_SELECT_SQL,
    candidate_aliases,
    dict_row,
    serialize_match,
)


def direct_alias_lookup(
    conn: Any,
    *,
    query: str,
    product_names: list[str],
    service_names: list[str],
    targets: list[str],
    business_line_hint: str = "",
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Exact normalized alias membership against product_catalog.aliases_normalized.

    Uses GIN(jsonb_ops) on aliases_normalized + ?| operator → bitmap index
    scan, supports many-to-many natively (one normalized alias hits all
    products that registered it).

    Multi-token customer phrases like 'Anti-CD19' miss this layer by
    design — they require either explicit alias materialization (the
    expand pass for CAR-T/mRNA) or trigram fallback in fuzzy_lookup.
    """
    aliases = candidate_aliases(
        query=query,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
    )
    if not aliases:
        return []

    normalized_aliases: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        n = normalize_object_alias(alias)
        if not n or n in seen:
            continue
        seen.add(n)
        normalized_aliases.append(n)
    if not normalized_aliases:
        return []

    conditions = ["p.aliases_normalized ?| %s", "p.is_active = TRUE"]
    params: list[Any] = [normalized_aliases]
    normalized_business_line = normalize_business_line_hint(business_line_hint)
    if normalized_business_line:
        conditions.append(BUSINESS_LINE_MATCH_SQL.format(field="p.business_line"))
        params.append(normalized_business_line)
    params.append(limit)

    sql = f"""
        {PRODUCT_SELECT_SQL},
        0.95 AS score,
        160 AS match_rank,
        'normalized_alias' AS matched_field,
        array_to_string(ARRAY(SELECT jsonb_array_elements_text(p.aliases)), ', ') AS matched_value
        FROM product_catalog p
        WHERE {" AND ".join(conditions)}
        ORDER BY p.catalog_no
        LIMIT %s
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [serialize_match(row) for row in cur.fetchall()]
