from __future__ import annotations

from src.ingestion.models import EntitySpan, IngestionBundle
from src.objects.models import AmbiguousObjectSet, ExtractorOutput, ObjectCandidate
from src.objects.registries.product_registry import (
    lookup_product_alias_matches,
    lookup_product_by_catalog_no,
    lookup_products_by_alias,
)


def _product_name(match: dict[str, object], fallback: str) -> str:
    return str(match.get("name") or match.get("canonical_name") or fallback)


def extract_product_candidates(ingestion_bundle: IngestionBundle) -> ExtractorOutput:
    parser_entities = ingestion_bundle.turn_signals.parser_signals.entities
    deterministic = ingestion_bundle.turn_signals.deterministic_signals

    candidates: list[ObjectCandidate] = []
    ambiguous_sets: list[AmbiguousObjectSet] = []

    for span in parser_entities.product_names:
        span_candidates, span_ambiguities = _extract_product_name_span(span)
        candidates.extend(span_candidates)
        ambiguous_sets.extend(span_ambiguities)

    for span in parser_entities.catalog_numbers:
        candidate = _extract_catalog_number_candidate(span.text, [span], "parser", 0.95)
        if candidate is not None:
            candidates.append(candidate)

    for span in deterministic.catalog_numbers:
        candidate = _extract_catalog_number_candidate(span.text, [span], "deterministic", 0.99)
        if candidate is not None:
            candidates.append(candidate)

    return ExtractorOutput(candidates=candidates, ambiguous_sets=ambiguous_sets)


def _extract_product_name_span(span: EntitySpan) -> tuple[list[ObjectCandidate], list[AmbiguousObjectSet]]:
    raw_value = span.normalized_value or span.text or span.raw
    matches = lookup_products_by_alias(raw_value)
    alias_matches = lookup_product_alias_matches(raw_value)
    alias_kinds = sorted({match.get("alias_kind", "") for match in alias_matches if match.get("alias_kind")})

    if len(matches) == 1:
        match = matches[0]
        product_name = _product_name(match, span.text)
        return [
            ObjectCandidate(
                object_type="product",
                raw_value=span.text,
                canonical_value=product_name,
                display_name=product_name,
                identifier=match.get("catalog_no", ""),
                identifier_type="catalog_no" if match.get("catalog_no") else "",
                business_line=match.get("business_line", ""),
                confidence=0.9,
                recency="CURRENT_TURN",
                source_type="parser",
                evidence_spans=[span],
                metadata={
                    "aliases": match.get("aliases", []),
                    "target_antigen": match.get("target_antigen", ""),
                    "application_text": match.get("application_text", ""),
                    "applications": match.get("applications", []),
                    "species_reactivity_text": match.get("species_reactivity_text", ""),
                    "format_or_size": match.get("format_or_size", ""),
                    "clone": match.get("clone", ""),
                    "clonality": match.get("clonality", ""),
                    "isotype": match.get("isotype", ""),
                    "ig_class": match.get("ig_class", ""),
                    "gene_id": match.get("gene_id", ""),
                    "gene_accession": match.get("gene_accession", ""),
                    "swissprot": match.get("swissprot", ""),
                    "costimulatory_domain": match.get("costimulatory_domain", ""),
                    "construct": match.get("construct", ""),
                    "product_type": match.get("product_type", ""),
                    "group_name": match.get("group_name", ""),
                    "group_type": match.get("group_type", ""),
                    "group_subtype": match.get("group_subtype", ""),
                    "group_summary": match.get("group_summary", ""),
                    "price_usd": match.get("price_usd", ""),
                    "unit": match.get("unit", ""),
                    "cell_number": match.get("cell_number", ""),
                    "marker": match.get("marker", ""),
                    "source_file": match.get("source_file", ""),
                    "source_sheet": match.get("source_sheet", ""),
                    "matched_alias": span.text,
                    "matched_alias_kinds": alias_kinds,
                    "alias_match_count": len(alias_matches),
                },
            )
        ], []

    if len(matches) > 1:
        ambiguous_candidates = [
            ObjectCandidate(
                object_type="product",
                raw_value=span.text,
                canonical_value=_product_name(match, span.text),
                display_name=_product_name(match, span.text),
                identifier=match.get("catalog_no", ""),
                identifier_type="catalog_no" if match.get("catalog_no") else "",
                business_line=match.get("business_line", ""),
                confidence=0.55,
                recency="CURRENT_TURN",
                source_type="parser",
                evidence_spans=[span],
                metadata={
                    "aliases": match.get("aliases", []),
                    "target_antigen": match.get("target_antigen", ""),
                    "application_text": match.get("application_text", ""),
                    "applications": match.get("applications", []),
                    "species_reactivity_text": match.get("species_reactivity_text", ""),
                    "format_or_size": match.get("format_or_size", ""),
                    "clonality": match.get("clonality", ""),
                    "isotype": match.get("isotype", ""),
                    "ig_class": match.get("ig_class", ""),
                    "costimulatory_domain": match.get("costimulatory_domain", ""),
                    "construct": match.get("construct", ""),
                    "group_name": match.get("group_name", ""),
                    "marker": match.get("marker", ""),
                    "match_strategy": "ambiguous_registry_alias",
                    "matched_alias": span.text,
                    "matched_alias_kinds": alias_kinds,
                    "alias_match_count": len(alias_matches),
                },
                is_ambiguous=True,
            )
            for match in matches
        ]
        return [], [
            AmbiguousObjectSet(
                object_type="product",
                query_value=span.text,
                candidates=ambiguous_candidates,
                resolution_strategy="clarify",
                reason="Multiple product registry entries matched the same alias.",
                attribute_constraints=[],
            )
        ]

    return [
        ObjectCandidate(
            object_type="product",
            raw_value=span.text,
            canonical_value=span.normalized_value or span.text,
            display_name=span.text,
            confidence=0.55,
            recency="CURRENT_TURN",
            source_type="parser",
            evidence_spans=[span],
            metadata={"match_strategy": "unresolved_product_name"},
        )
    ], []


def _extract_catalog_number_candidate(
    catalog_no: str,
    evidence_spans: list[EntitySpan],
    source_type: str,
    confidence: float,
) -> ObjectCandidate | None:
    match = lookup_product_by_catalog_no(catalog_no)
    if match is None:
        return ObjectCandidate(
            object_type="product",
            raw_value=catalog_no,
            canonical_value=catalog_no,
            display_name=catalog_no,
            identifier=catalog_no,
            identifier_type="catalog_no",
            confidence=confidence * 0.7,
            recency="CURRENT_TURN",
            source_type=source_type,
            evidence_spans=evidence_spans,
            metadata={"match_strategy": "unknown_catalog_no"},
        )

    return ObjectCandidate(
        object_type="product",
        raw_value=catalog_no,
        canonical_value=_product_name(match, catalog_no),
        display_name=_product_name(match, catalog_no),
        identifier=match.get("catalog_no", "") or catalog_no,
        identifier_type="catalog_no",
        business_line=match.get("business_line", ""),
        confidence=confidence,
        recency="CURRENT_TURN",
        source_type=source_type,
        evidence_spans=evidence_spans,
        metadata={
            "aliases": match.get("aliases", []),
            "target_antigen": match.get("target_antigen", ""),
            "application_text": match.get("application_text", ""),
            "applications": match.get("applications", []),
            "species_reactivity_text": match.get("species_reactivity_text", ""),
            "format_or_size": match.get("format_or_size", ""),
            "clone": match.get("clone", ""),
            "clonality": match.get("clonality", ""),
            "isotype": match.get("isotype", ""),
            "ig_class": match.get("ig_class", ""),
            "gene_id": match.get("gene_id", ""),
            "gene_accession": match.get("gene_accession", ""),
            "swissprot": match.get("swissprot", ""),
            "costimulatory_domain": match.get("costimulatory_domain", ""),
            "construct": match.get("construct", ""),
            "product_type": match.get("product_type", ""),
            "group_name": match.get("group_name", ""),
            "group_type": match.get("group_type", ""),
            "group_subtype": match.get("group_subtype", ""),
            "group_summary": match.get("group_summary", ""),
            "price_usd": match.get("price_usd", ""),
            "unit": match.get("unit", ""),
            "cell_number": match.get("cell_number", ""),
            "marker": match.get("marker", ""),
            "source_file": match.get("source_file", ""),
            "source_sheet": match.get("source_sheet", ""),
        },
    )
