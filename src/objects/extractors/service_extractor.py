from __future__ import annotations

from src.ingestion.models import EntitySpan, IngestionBundle
from src.objects.models import AmbiguousObjectSet, ExtractorOutput, ObjectCandidate
from src.objects.registries.service_registry import lookup_service_alias_matches, lookup_services_by_alias


def extract_service_candidates(ingestion_bundle: IngestionBundle) -> ExtractorOutput:
    parser_entities = ingestion_bundle.turn_signals.parser_signals.entities

    candidates: list[ObjectCandidate] = []
    ambiguous_sets: list[AmbiguousObjectSet] = []

    for span in parser_entities.service_names:
        span_candidates, span_ambiguities = _extract_service_name_span(span)
        candidates.extend(span_candidates)
        ambiguous_sets.extend(span_ambiguities)

    return ExtractorOutput(candidates=candidates, ambiguous_sets=ambiguous_sets)


def _extract_service_name_span(span: EntitySpan) -> tuple[list[ObjectCandidate], list[AmbiguousObjectSet]]:
    raw_value = span.normalized_value or span.text or span.raw
    matches = lookup_services_by_alias(raw_value)
    alias_matches = lookup_service_alias_matches(raw_value)
    alias_kinds = sorted({match.get("alias_kind", "") for match in alias_matches if match.get("alias_kind")})

    if len(matches) == 1:
        match = matches[0]
        canonical_name = match.get("canonical_name", "") or span.text
        return [
            ObjectCandidate(
                object_type="service",
                raw_value=span.text,
                canonical_value=canonical_name,
                display_name=canonical_name,
                identifier=canonical_name,
                identifier_type="service_name",
                business_line=match.get("business_line", ""),
                confidence=0.88,
                recency="CURRENT_TURN",
                source_type="parser",
                evidence_spans=[span],
                metadata={
                    "aliases": match.get("aliases", []),
                    "service_line": match.get("service_line", ""),
                    "subcategory": match.get("subcategory", ""),
                    "page_title": match.get("page_title", ""),
                    "document_summary": match.get("document_summary", ""),
                    "source_url": match.get("source_url", ""),
                    "source_path": match.get("source_path", ""),
                    "source_file": match.get("source_file", ""),
                    "matched_alias": span.text,
                    "matched_alias_kinds": alias_kinds,
                    "alias_match_count": len(alias_matches),
                },
            )
        ], []

    if len(matches) > 1:
        ambiguous_candidates = [
            ObjectCandidate(
                object_type="service",
                raw_value=span.text,
                canonical_value=match.get("canonical_name", "") or span.text,
                display_name=match.get("canonical_name", "") or span.text,
                identifier=match.get("canonical_name", "") or "",
                identifier_type="service_name",
                business_line=match.get("business_line", ""),
                confidence=0.55,
                recency="CURRENT_TURN",
                source_type="parser",
                evidence_spans=[span],
                metadata={
                    "aliases": match.get("aliases", []),
                    "match_strategy": "ambiguous_service_alias",
                    "service_line": match.get("service_line", ""),
                    "subcategory": match.get("subcategory", ""),
                    "source_url": match.get("source_url", ""),
                    "source_path": match.get("source_path", ""),
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
                object_type="service",
                query_value=span.text,
                candidates=ambiguous_candidates,
                resolution_strategy="clarify",
                reason="Multiple service registry entries matched the same alias or phrase fragment.",
            )
        ]

    return [
        ObjectCandidate(
            object_type="service",
            raw_value=span.text,
            canonical_value=span.normalized_value or span.text,
            display_name=span.text,
            identifier=span.text,
            identifier_type="service_name",
            confidence=0.52,
            recency="CURRENT_TURN",
            source_type="parser",
            evidence_spans=[span],
            metadata={"match_strategy": "unresolved_service_name"},
        )
    ], []
