from __future__ import annotations

from typing import Any

from .normalization import DEFAULT_LIMIT, clean_text, extract_catalog_numbers
from .ranking import rank_catalog_matches
from src.objects.registries.product_registry import lookup_product_by_catalog_no, lookup_products_by_alias
from .retrieval import catalog_number_lookup, direct_alias_lookup, fuzzy_lookup
from .retrieval.shared import build_connection_string, psycopg


def _registry_match(entry: dict[str, Any], *, retrieval_mode: str, score: float, rank: int) -> dict[str, Any]:
    product_name = entry.get("name") or entry.get("canonical_name") or ""
    return {
        "id": entry.get("catalog_no") or "",
        "catalog_no": entry.get("catalog_no") or "",
        "name": product_name,
        "display_name": product_name,
        "business_line": entry.get("business_line") or "",
        "target_antigen": entry.get("target_antigen") or "",
        "application_text": entry.get("application_text") or "",
        "species_reactivity_text": entry.get("species_reactivity_text") or "",
        "score": score,
        "match_rank": rank,
        "retrieval_mode": retrieval_mode,
        "source_file": entry.get("source_file") or "",
        "source_sheet": entry.get("source_sheet") or "",
    }


def _registry_fallback_matches(
    *,
    catalog_numbers: list[str],
    product_names: list[str],
    targets: list[str],
    top_k: int,
) -> tuple[list[dict[str, Any]], str]:
    matches: list[dict[str, Any]] = []
    seen_catalogs: set[str] = set()

    for catalog_no in catalog_numbers:
        entry = lookup_product_by_catalog_no(catalog_no)
        if not entry:
            continue
        normalized_catalog = str(entry.get("catalog_no") or "").strip().upper()
        if not normalized_catalog or normalized_catalog in seen_catalogs:
            continue
        seen_catalogs.add(normalized_catalog)
        matches.append(
            _registry_match(
                entry,
                retrieval_mode="local_registry_catalog_number",
                score=1.0,
                rank=100,
            )
        )

    alias_queries = [*product_names, *targets]
    for alias in alias_queries:
        for entry in lookup_products_by_alias(alias):
            normalized_catalog = str(entry.get("catalog_no") or "").strip().upper()
            if not normalized_catalog or normalized_catalog in seen_catalogs:
                continue
            seen_catalogs.add(normalized_catalog)
            matches.append(
                _registry_match(
                    entry,
                    retrieval_mode="local_registry_alias",
                    score=0.86,
                    rank=60,
                )
            )

    return rank_catalog_matches(matches, top_k=top_k), ("local_registry_catalog_number" if catalog_numbers else "local_registry_alias")


def _seed_catalog_numbers_from_registry_aliases(
    *,
    catalog_numbers: list[str],
    product_names: list[str],
    targets: list[str],
) -> list[str]:
    if catalog_numbers:
        return catalog_numbers

    candidate_catalogs: list[str] = []
    seen: set[str] = set()
    for alias in [*product_names, *targets]:
        matches = lookup_products_by_alias(alias)
        unique_catalogs = {
            str(match.get("catalog_no") or "").strip().upper()
            for match in matches
            if str(match.get("catalog_no") or "").strip()
        }
        if len(unique_catalogs) != 1:
            continue
        catalog_no = next(iter(unique_catalogs))
        if catalog_no in seen:
            continue
        seen.add(catalog_no)
        candidate_catalogs.append(catalog_no)

    return candidate_catalogs if len(candidate_catalogs) == 1 else catalog_numbers


def _has_structured_entity_scope(
    *,
    catalog_numbers: list[str],
    product_names: list[str],
    service_names: list[str],
    targets: list[str],
) -> bool:
    return bool(catalog_numbers or product_names or service_names or targets)


def _tier_one_lookup(
    conn: Any,
    *,
    catalog_numbers: list[str],
    business_line_hint: str,
    top_k: int,
) -> tuple[list[dict[str, Any]], str]:
    if not catalog_numbers:
        return [], ""
    matches = catalog_number_lookup(
        conn,
        catalog_numbers=catalog_numbers,
        business_line_hint=business_line_hint,
        limit=top_k,
    )
    return matches, ("exact_lookup" if matches else "")


def _tier_two_lookup(
    conn: Any,
    *,
    query: str,
    product_names: list[str],
    service_names: list[str],
    targets: list[str],
    business_line_hint: str,
    top_k: int,
) -> tuple[list[dict[str, Any]], str]:
    if not _has_structured_entity_scope(
        catalog_numbers=[],
        product_names=product_names,
        service_names=service_names,
        targets=targets,
    ):
        return [], ""

    matches = direct_alias_lookup(
        conn,
        query=query,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
        business_line_hint=business_line_hint,
        limit=top_k,
    )
    if matches:
        return matches, "direct_alias_lookup"

    return [], ""


def _tier_three_lookup(
    conn: Any,
    *,
    query: str,
    catalog_numbers: list[str],
    product_names: list[str],
    service_names: list[str],
    targets: list[str],
    applications: list[str],
    species: list[str],
    format_or_size: str,
    business_line_hint: str,
    top_k: int,
) -> tuple[list[dict[str, Any]], str]:
    matches = fuzzy_lookup(
        conn,
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
    return matches, ("fuzzy_lookup" if matches else "")


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
    catalog_numbers = _seed_catalog_numbers_from_registry_aliases(
        catalog_numbers=catalog_numbers,
        product_names=product_names,
        targets=targets,
    )

    if psycopg is None:
        fallback_matches, fallback_mode = _registry_fallback_matches(
            catalog_numbers=catalog_numbers,
            product_names=product_names,
            targets=targets,
            top_k=top_k,
        )
        return {
            "lookup_mode": "local_registry_fallback" if fallback_matches else "postgresql_catalog",
            "retrieval_tier": "tier_1" if catalog_numbers else ("tier_2" if _has_structured_entity_scope(catalog_numbers=[], product_names=product_names, service_names=service_names, targets=targets) else "tier_3"),
            "retrieval_mode": fallback_mode if fallback_matches else "",
            "match_status": "matched" if fallback_matches else "driver_missing",
            "query": effective_query,
            "catalog_numbers": catalog_numbers,
            "product_names": product_names,
            "service_names": service_names,
            "targets": targets,
            "applications": applications,
            "species": species,
            "format_or_size": format_or_size,
            "matches": fallback_matches,
            "message": "Matched using the local product registry because psycopg is not installed." if fallback_matches else "psycopg is not installed.",
        }

    retrieval_mode = ""
    retrieval_tier = ""
    try:
        with psycopg.connect(build_connection_string()) as conn:
            matches, retrieval_mode = _tier_one_lookup(
                conn,
                catalog_numbers=catalog_numbers,
                business_line_hint=business_line_hint,
                top_k=top_k,
            )
            if matches:
                retrieval_tier = "tier_1"

            if not matches:
                matches, retrieval_mode = _tier_two_lookup(
                    conn,
                    query=effective_query,
                    product_names=product_names,
                    service_names=service_names,
                    targets=targets,
                    business_line_hint=business_line_hint,
                    top_k=top_k,
                )
                if matches:
                    retrieval_tier = "tier_2"

            if not matches:
                matches, retrieval_mode = _tier_three_lookup(
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
                    retrieval_tier = "tier_3"
    except Exception as exc:  # pragma: no cover
        fallback_matches, fallback_mode = _registry_fallback_matches(
            catalog_numbers=catalog_numbers,
            product_names=product_names,
            targets=targets,
            top_k=top_k,
        )
        return {
            "lookup_mode": "local_registry_fallback" if fallback_matches else "postgresql_catalog",
            "retrieval_tier": "tier_1" if catalog_numbers else ("tier_2" if _has_structured_entity_scope(catalog_numbers=[], product_names=product_names, service_names=service_names, targets=targets) else "tier_3"),
            "retrieval_mode": fallback_mode if fallback_matches else "",
            "match_status": "matched" if fallback_matches else "connection_failed",
            "query": effective_query,
            "catalog_numbers": catalog_numbers,
            "product_names": product_names,
            "service_names": service_names,
            "targets": targets,
            "applications": applications,
            "species": species,
            "format_or_size": format_or_size,
            "matches": fallback_matches,
            "message": f"Matched using the local product registry after catalog backend failure: {exc}" if fallback_matches else str(exc),
        }

    ranked_matches = rank_catalog_matches(matches, top_k=top_k)

    return {
        "lookup_mode": "postgresql_catalog",
        "retrieval_tier": retrieval_tier or ("tier_1" if catalog_numbers else ("tier_2" if _has_structured_entity_scope(catalog_numbers=[], product_names=product_names, service_names=service_names, targets=targets) else "tier_3")),
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
