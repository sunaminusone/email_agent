from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.documents.retrieval.service_documents import (
    SERVICE_CATALOG_TABLE,
    SERVICE_DOCUMENTS_TABLE,
    build_connection_string,
)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - psycopg is required at runtime
    psycopg = None
    dict_row = None


@lru_cache(maxsize=1)
def document_catalog_inventory(
    *,
    infer_document_type,
    normalize_text,
    tokenize,
    normalize_business_line,
) -> list[dict[str, Any]]:
    """Read document inventory from Postgres.

    Returns two kinds of entries, each shaped identically so the
    selection ranker can score them with the same logic:
      * service-level documents (service_documents joined to service_catalog)
        — product_scope="service_line", catalog_no=""
      * product-level flyers (cart_/lnp_product_catalog.flyer_s3_url joined
        to product_catalog) — product_scope="product", catalog_no=PM-…

    Rows lacking storage_url are skipped — presigned URLs are minted
    later by the caller, only for top-ranked matches.
    """
    if psycopg is None:
        return []

    service_sql = f"""
        SELECT
            sd.file_name,
            sd.title,
            sd.document_type,
            sd.storage_url,
            sd.metadata,
            sc.canonical_name AS service_name,
            sc.business_line
        FROM {SERVICE_DOCUMENTS_TABLE} sd
        JOIN {SERVICE_CATALOG_TABLE} sc ON sd.service_id = sc.id
        WHERE sd.is_active = TRUE
    """

    # CAR-T + mRNA-LNP product flyers. UNION ALL the two CTI children so
    # callers don't need to know the schema split. file_name is derived
    # from the URL basename (we don't store it separately on the catalog
    # rows). title is "<catalog_no> Product Flyer" — short, identifies the
    # SKU, matches the convention CSR draft prompt uses for the markdown
    # link label.
    product_flyer_sql = """
        SELECT
            p.catalog_no,
            p.name AS product_name,
            p.business_line,
            cc.flyer_s3_url AS storage_url,
            regexp_replace(cc.flyer_s3_url, '.*/', '') AS file_name
        FROM product_catalog p
        JOIN cart_product_catalog cc ON cc.product_id = p.id
        WHERE cc.flyer_s3_url IS NOT NULL
        UNION ALL
        SELECT
            p.catalog_no,
            p.name AS product_name,
            p.business_line,
            lp.flyer_s3_url AS storage_url,
            regexp_replace(lp.flyer_s3_url, '.*/', '') AS file_name
        FROM product_catalog p
        JOIN lnp_product_catalog lp ON lp.product_id = p.id
        WHERE lp.flyer_s3_url IS NOT NULL
    """

    # No try/except: let PG exceptions propagate so documentation_tool
    # surfaces them as ToolResult.status="error" with the underlying
    # error text. Catching here previously masked connection failures
    # as "no documents in inventory", and the lru_cache would freeze the
    # empty result for the rest of the process lifetime. Propagating
    # also means lru_cache won't cache the failure — next call retries.
    with psycopg.connect(build_connection_string()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(service_sql)
            service_rows = cur.fetchall()
            cur.execute(product_flyer_sql)
            product_flyer_rows = cur.fetchall()

    inventory: list[dict[str, Any]] = []

    for row in service_rows:
        storage_url = (row.get("storage_url") or "").strip()
        if not storage_url:
            continue

        file_name = (row.get("file_name") or "").strip()
        title = (row.get("title") or "").strip() or file_name
        document_type = (row.get("document_type") or "").strip() or infer_document_type(file_name)
        business_line = (row.get("business_line") or "").strip()
        service_name = (row.get("service_name") or "").strip()

        search_blob = " ".join(
            part for part in [file_name, title, service_name, business_line, document_type] if part
        )

        inventory.append(
            {
                "file_name": file_name,
                "source_path": storage_url,
                "storage_url": storage_url,
                "document_type": document_type,
                "business_line": business_line,
                "normalized_business_line": normalize_business_line(business_line),
                "title": title,
                "product_scope": "service_line",
                "product_name": service_name,
                "catalog_no": "",
                "normalized_name": normalize_text(search_blob),
                "tokens": tokenize(search_blob),
            }
        )

    for row in product_flyer_rows:
        storage_url = (row.get("storage_url") or "").strip()
        if not storage_url:
            continue

        catalog_no = (row.get("catalog_no") or "").strip()
        product_name = (row.get("product_name") or "").strip()
        business_line = (row.get("business_line") or "").strip()
        file_name = (row.get("file_name") or "").strip()
        title = f"{catalog_no} Product Flyer" if catalog_no else (file_name or "Product Flyer")

        # Include catalog_no in the search blob so token matches in
        # run_document_selection score this row when the customer's
        # query contains the SKU. business_line + "flyer" round it out
        # for natural-language asks like "CAR-T flyers".
        search_blob = " ".join(
            part for part in [catalog_no, product_name, business_line, "flyer", file_name] if part
        )

        inventory.append(
            {
                "file_name": file_name,
                "source_path": storage_url,
                "storage_url": storage_url,
                "document_type": "flyer",
                "business_line": business_line,
                "normalized_business_line": normalize_business_line(business_line),
                "title": title,
                "product_scope": "product",
                "product_name": product_name,
                "catalog_no": catalog_no,
                "normalized_name": normalize_text(search_blob),
                "tokens": tokenize(search_blob),
            }
        )

    return inventory
