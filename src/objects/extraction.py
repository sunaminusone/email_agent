from __future__ import annotations

from typing import TYPE_CHECKING

from src.ingestion.models import IngestionBundle
from src.objects.extractors.context_extractor import extract_context_candidates
from src.objects.extractors.operational_extractor import extract_operational_candidates
from src.objects.extractors.product_extractor import extract_product_candidates
from src.objects.extractors.service_extractor import extract_service_candidates
from src.objects.models import AmbiguousObjectSet, ObjectBundle, ObjectCandidate
from src.objects.normalizers import normalize_identifier, normalize_object_alias

if TYPE_CHECKING:
    from src.memory.models import ScoredObjectRef


def extract_object_bundle(
    ingestion_bundle: IngestionBundle,
    recent_objects: list[ScoredObjectRef] | None = None,
) -> ObjectBundle:
    extractor_outputs = [
        extract_product_candidates(ingestion_bundle),
        extract_service_candidates(ingestion_bundle),
        extract_operational_candidates(ingestion_bundle),
        extract_context_candidates(ingestion_bundle, recent_objects=recent_objects),
    ]

    current_candidates: list[ObjectCandidate] = []
    context_candidates: list[ObjectCandidate] = []
    ambiguous_sets: list[AmbiguousObjectSet] = []

    for output in extractor_outputs:
        deduped_candidates = _dedupe_candidates(output.candidates)
        for candidate in deduped_candidates:
            if candidate.recency == "CONTEXTUAL" or candidate.source_type == "stateful_anchor":
                context_candidates.append(candidate)
            else:
                current_candidates.append(candidate)
        ambiguous_sets.extend(output.ambiguous_sets)

    current_candidates = _dedupe_candidates(current_candidates)
    context_candidates = _dedupe_candidates(context_candidates)
    all_candidates = _dedupe_candidates([*current_candidates, *context_candidates])
    ambiguous_sets = _dedupe_ambiguous_sets(ambiguous_sets)

    return ObjectBundle(
        current_candidates=current_candidates,
        context_candidates=context_candidates,
        all_candidates=all_candidates,
        ambiguous_sets=ambiguous_sets,
    )


def _dedupe_candidates(candidates: list[ObjectCandidate]) -> list[ObjectCandidate]:
    by_key: dict[tuple[str, str, str], ObjectCandidate] = {}

    for candidate in candidates:
        key = _candidate_key(candidate)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = candidate
            continue
        by_key[key] = _merge_candidates(existing, candidate)

    return list(by_key.values())


def _candidate_key(candidate: ObjectCandidate) -> tuple[str, str, str]:
    if candidate.identifier:
        return (
            candidate.object_type,
            candidate.identifier_type or "identifier",
            normalize_identifier(candidate.identifier),
        )
    return (
        candidate.object_type,
        "value",
        normalize_object_alias(candidate.canonical_value or candidate.display_name or candidate.raw_value),
    )


def _merge_candidates(left: ObjectCandidate, right: ObjectCandidate) -> ObjectCandidate:
    primary = left if left.confidence >= right.confidence else right
    secondary = right if primary is left else left

    merged_spans = [*primary.evidence_spans]
    for span in secondary.evidence_spans:
        if span not in merged_spans:
            merged_spans.append(span)

    merged_constraints = [*primary.attribute_constraints]
    for constraint in secondary.attribute_constraints:
        if constraint not in merged_constraints:
            merged_constraints.append(constraint)

    merged_metadata = {**secondary.metadata, **primary.metadata}
    return primary.model_copy(
        update={
            "confidence": max(left.confidence, right.confidence),
            "evidence_spans": merged_spans,
            "attribute_constraints": merged_constraints,
            "metadata": merged_metadata,
            "used_stateful_anchor": left.used_stateful_anchor or right.used_stateful_anchor,
            "is_ambiguous": left.is_ambiguous or right.is_ambiguous,
        }
    )


def _dedupe_ambiguous_sets(ambiguous_sets: list[AmbiguousObjectSet]) -> list[AmbiguousObjectSet]:
    by_key: dict[tuple[str, str], AmbiguousObjectSet] = {}
    for ambiguous_set in ambiguous_sets:
        key = (
            ambiguous_set.object_type,
            normalize_object_alias(ambiguous_set.query_value),
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = ambiguous_set
            continue

        merged_candidates = _dedupe_candidates([*existing.candidates, *ambiguous_set.candidates])
        by_key[key] = existing.model_copy(update={"candidates": merged_candidates})

    return list(by_key.values())
