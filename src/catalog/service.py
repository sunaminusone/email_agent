from __future__ import annotations

from typing import Any

from .retrieval.shared import build_connection_string, psycopg
from .selection import run_catalog_selection


def catalog_backend_status() -> dict[str, Any]:
    if psycopg is None:
        return {
            "connected": False,
            "status": "driver_missing",
            "message": "psycopg is not installed.",
        }

    connection_string = build_connection_string()
    try:
        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as exc:  # pragma: no cover
        return {
            "connected": False,
            "status": "connection_failed",
            "message": str(exc),
        }

    return {
        "connected": True,
        "status": "ok",
    }


def lookup_catalog_products(
    *,
    query: str,
    catalog_numbers: list[str] | None = None,
    product_names: list[str] | None = None,
    service_names: list[str] | None = None,
    targets: list[str] | None = None,
    applications: list[str] | None = None,
    species: list[str] | None = None,
    format_or_size: str = "",
    business_line_hint: str = "",
    top_k: int = 10,
) -> dict[str, Any]:
    return run_catalog_selection(
        query=query,
        catalog_numbers=catalog_numbers,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
        applications=applications,
        species=species,
        format_or_size=format_or_size,
        business_line_hint=business_line_hint,
        top_k=top_k,
    )
