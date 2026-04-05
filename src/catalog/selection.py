from __future__ import annotations

from typing import Any

from .normalization import DEFAULT_LIMIT, clean_text, extract_catalog_numbers
from .ranking import rank_catalog_matches
from .retrieval import alias_lookup, catalog_number_lookup, direct_alias_lookup, fuzzy_lookup
from .retrieval.shared import build_connection_string, psycopg


def run_catalog_selection(
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
    top_k: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    catalog_numbers = [clean_text(value).upper() for value in (catalog_numbers or []) if clean_text(value)]
    product_names = [clean_text(value) for value in (product_names or []) if clean_text(value)]
    service_names = [clean_text(value) for value in (service_names or []) if clean_text(value)]
    targets = [clean_text(value) for value in (targets or []) if clean_text(value)]
    applications = [clean_text(value) for value in (applications or []) if clean_text(value)]
    species = [clean_text(value) for value in (species or []) if clean_text(value)]
    format_or_size = clean_text(format_or_size)
    effective_query = clean_text(query) or " ".join(catalog_numbers + product_names + service_names + targets)
    inferred_catalog_numbers = extract_catalog_numbers(effective_query, *product_names, *service_names)
    catalog_numbers = list(dict.fromkeys(catalog_numbers + inferred_catalog_numbers))

    if psycopg is None:
        return {
            "lookup_mode": "postgresql_catalog",
            "match_status": "driver_missing",
            "query": effective_query,
            "catalog_numbers": catalog_numbers,
            "product_names": product_names,
            "service_names": service_names,
            "targets": targets,
            "applications": applications,
            "species": species,
            "format_or_size": format_or_size,
            "matches": [],
            "message": "psycopg is not installed.",
        }

    retrieval_mode = ""
    try:
        with psycopg.connect(build_connection_string()) as conn:
            matches = catalog_number_lookup(
                conn,
                catalog_numbers=catalog_numbers,
                business_line_hint=business_line_hint,
                limit=top_k,
            )
            if matches:
                retrieval_mode = "exact_lookup"
            if not matches:
                matches = alias_lookup(
                    conn,
                    query=effective_query,
                    product_names=product_names,
                    service_names=service_names,
                    targets=targets,
                    business_line_hint=business_line_hint,
                    limit=top_k,
                )
                if matches:
                    retrieval_mode = "alias_lookup"
            if not matches:
                matches = direct_alias_lookup(
                    conn,
                    query=effective_query,
                    product_names=product_names,
                    service_names=service_names,
                    targets=targets,
                    business_line_hint=business_line_hint,
                    limit=top_k,
                )
                if matches:
                    retrieval_mode = "direct_alias_lookup"
            if not matches:
                matches = fuzzy_lookup(
                    conn,
                    query=effective_query,
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
                if matches:
                    retrieval_mode = "fuzzy_lookup"
    except Exception as exc:  # pragma: no cover
        return {
            "lookup_mode": "postgresql_catalog",
            "match_status": "connection_failed",
            "query": effective_query,
            "catalog_numbers": catalog_numbers,
            "product_names": product_names,
            "service_names": service_names,
            "targets": targets,
            "applications": applications,
            "species": species,
            "format_or_size": format_or_size,
            "matches": [],
            "message": str(exc),
        }

    ranked_matches = rank_catalog_matches(matches, top_k=top_k)

    return {
        "lookup_mode": "postgresql_catalog",
        "retrieval_mode": retrieval_mode,
        "match_status": "matched" if ranked_matches else "not_found",
        "query": effective_query,
        "catalog_numbers": catalog_numbers,
        "product_names": product_names,
        "service_names": service_names,
        "targets": targets,
        "applications": applications,
        "species": species,
        "format_or_size": format_or_size,
        "business_line_hint": business_line_hint,
        "matches": ranked_matches,
    }
