from __future__ import annotations

from collections.abc import Iterable

from src.ingestion.models import AttributeConstraint
from src.objects.models import AmbiguousObjectSet, ObjectCandidate
from src.objects.normalizers import normalize_object_alias


def attach_constraints_to_candidates(
    candidates: list[ObjectCandidate],
    constraints: list[AttributeConstraint],
) -> list[ObjectCandidate]:
    if not constraints:
        return candidates

    return [
        candidate.model_copy(
            update={
                "attribute_constraints": _merge_constraints(
                    candidate.attribute_constraints,
                    constraints,
                )
            }
        )
        for candidate in candidates
    ]


def attach_constraints_to_ambiguous_sets(
    ambiguous_sets: list[AmbiguousObjectSet],
    constraints: list[AttributeConstraint],
) -> list[AmbiguousObjectSet]:
    if not constraints:
        return ambiguous_sets

    updated_sets: list[AmbiguousObjectSet] = []
    for ambiguous_set in ambiguous_sets:
        updated_sets.append(
            ambiguous_set.model_copy(
                update={
                    "attribute_constraints": _merge_constraints(
                        ambiguous_set.attribute_constraints,
                        constraints,
                    ),
                    "candidates": attach_constraints_to_candidates(
                        ambiguous_set.candidates,
                        constraints,
                    ),
                }
            )
        )
    return updated_sets


def filter_candidates_by_constraints(
    candidates: list[ObjectCandidate],
    constraints: list[AttributeConstraint],
) -> list[ObjectCandidate]:
    if not constraints:
        return candidates
    return [
        candidate
        for candidate in candidates
        if all(candidate_matches_constraint(candidate, constraint) for constraint in constraints)
    ]


def filter_ambiguous_sets_by_constraints(
    ambiguous_sets: list[AmbiguousObjectSet],
    constraints: list[AttributeConstraint],
) -> tuple[list[AmbiguousObjectSet], list[ObjectCandidate]]:
    if not constraints:
        return ambiguous_sets, []

    remaining_sets: list[AmbiguousObjectSet] = []
    promoted_candidates: list[ObjectCandidate] = []

    for ambiguous_set in ambiguous_sets:
        filtered_candidates = filter_candidates_by_constraints(ambiguous_set.candidates, constraints)
        if not filtered_candidates:
            continue
        if len(filtered_candidates) == 1:
            promoted_candidates.append(filtered_candidates[0])
            continue
        remaining_sets.append(
            ambiguous_set.model_copy(
                update={
                    "candidates": filtered_candidates,
                    "attribute_constraints": _merge_constraints(
                        ambiguous_set.attribute_constraints,
                        constraints,
                    ),
                }
            )
        )

    return remaining_sets, promoted_candidates


def candidate_matches_constraint(candidate: ObjectCandidate, constraint: AttributeConstraint) -> bool:
    attribute = normalize_object_alias(constraint.attribute)
    value = normalize_object_alias(constraint.value)
    if not value:
        return True

    if candidate.object_type == "product":
        haystacks = _product_attribute_haystacks(candidate)
    elif candidate.object_type == "service":
        haystacks = _service_attribute_haystacks(candidate)
    else:
        haystacks = _generic_attribute_haystacks(candidate)

    if attribute == "species":
        return _matches_any(value, haystacks["species"])
    if attribute == "application or validation":
        return _matches_any(value, haystacks["application_or_validation"])
    if attribute == "format or size":
        return _matches_any(value, haystacks["format_or_size"])
    if attribute == "clonality":
        return _matches_any(value, haystacks["clonality"])
    if attribute == "business line":
        return _matches_any(value, haystacks["business_line"])
    if attribute == "isotype":
        return _matches_any(value, haystacks["isotype"], exact_only=True)
    if attribute == "costim domain":
        return _matches_any(value, haystacks["costim_domain"], exact_only=True)
    if attribute == "car t group":
        return _matches_any(value, haystacks["car_t_group"], exact_only=True)
    if attribute == "descriptive filter":
        return _matches_any(value, haystacks["descriptive_filter"])

    return _matches_any(value, haystacks["descriptive_filter"])


def _product_attribute_haystacks(candidate: ObjectCandidate) -> dict[str, list[str]]:
    metadata = candidate.metadata
    aliases = metadata.get("aliases", [])
    alias_values = [str(alias) for alias in aliases] if isinstance(aliases, list) else []

    species_values = [
        metadata.get("species_reactivity_text", ""),
        metadata.get("target_antigen", ""),
        candidate.display_name,
        candidate.canonical_value,
        *alias_values,
    ]
    application_values = [
        metadata.get("application_text", ""),
        metadata.get("group_summary", ""),
        metadata.get("construct", ""),
        candidate.display_name,
        candidate.canonical_value,
        *alias_values,
    ]
    format_values = [
        metadata.get("format", ""),
        metadata.get("format_or_size", ""),
        metadata.get("unit", ""),
        metadata.get("cell_number", ""),
        candidate.display_name,
        candidate.canonical_value,
        candidate.raw_value,
        *alias_values,
    ]
    clonality_values = [
        metadata.get("clonality", ""),
        metadata.get("clone", ""),
        candidate.display_name,
        candidate.canonical_value,
        *alias_values,
    ]
    business_line_values = [
        candidate.business_line,
        candidate.object_type,
        metadata.get("product_type", ""),
        metadata.get("group_type", ""),
        metadata.get("group_subtype", ""),
        candidate.display_name,
    ]
    descriptive_values = [
        candidate.raw_value,
        candidate.display_name,
        candidate.canonical_value,
        candidate.identifier,
        candidate.business_line,
        metadata.get("target_antigen", ""),
        metadata.get("application_text", ""),
        metadata.get("species_reactivity_text", ""),
        metadata.get("format", ""),
        metadata.get("format_or_size", ""),
        metadata.get("clonality", ""),
        metadata.get("clone", ""),
        metadata.get("construct", ""),
        metadata.get("product_type", ""),
        metadata.get("group_name", ""),
        metadata.get("group_type", ""),
        metadata.get("group_subtype", ""),
        metadata.get("marker", ""),
        *alias_values,
    ]

    isotype_values = [
        metadata.get("isotype", ""),
        metadata.get("ig_class", ""),
    ]
    costim_values = [
        metadata.get("costimulatory_domain", ""),
    ]
    car_t_group_values = [
        metadata.get("group_name", ""),
        metadata.get("group_type", ""),
        metadata.get("group_subtype", ""),
    ]

    return {
        "species": _normalize_values(species_values),
        "application_or_validation": _normalize_values(application_values),
        "format_or_size": _normalize_values(format_values),
        "clonality": _normalize_values(clonality_values),
        "business_line": _normalize_values(business_line_values),
        "isotype": _normalize_values(isotype_values),
        "costim_domain": _normalize_values(costim_values),
        "car_t_group": _normalize_values(car_t_group_values),
        "descriptive_filter": _normalize_values(descriptive_values),
    }


def _service_attribute_haystacks(candidate: ObjectCandidate) -> dict[str, list[str]]:
    metadata = candidate.metadata
    aliases = metadata.get("aliases", [])
    alias_values = [str(alias) for alias in aliases] if isinstance(aliases, list) else []

    business_line_values = [
        candidate.business_line,
        metadata.get("service_line", ""),
        metadata.get("subcategory", ""),
        candidate.object_type,
        candidate.display_name,
    ]
    application_values = [
        metadata.get("service_line", ""),
        metadata.get("subcategory", ""),
        metadata.get("page_title", ""),
        candidate.display_name,
        candidate.canonical_value,
        *alias_values,
    ]
    descriptive_values = [
        candidate.raw_value,
        candidate.display_name,
        candidate.canonical_value,
        candidate.identifier,
        candidate.business_line,
        metadata.get("service_line", ""),
        metadata.get("subcategory", ""),
        metadata.get("page_title", ""),
        metadata.get("document_summary", ""),
        *alias_values,
    ]

    return {
        "species": [],
        "application_or_validation": _normalize_values(application_values),
        "format_or_size": [],
        "clonality": [],
        "business_line": _normalize_values(business_line_values),
        "isotype": [],
        "costim_domain": [],
        "car_t_group": [],
        "descriptive_filter": _normalize_values(descriptive_values),
    }


def _generic_attribute_haystacks(candidate: ObjectCandidate) -> dict[str, list[str]]:
    metadata = candidate.metadata
    aliases = metadata.get("aliases", [])
    alias_values = [str(alias) for alias in aliases] if isinstance(aliases, list) else []

    descriptive_values = [
        candidate.raw_value,
        candidate.display_name,
        candidate.canonical_value,
        candidate.identifier,
        candidate.business_line,
        *alias_values,
    ]

    return {
        "species": _normalize_values([candidate.display_name, candidate.canonical_value, *alias_values]),
        "application_or_validation": _normalize_values([candidate.display_name, candidate.canonical_value, *alias_values]),
        "format_or_size": _normalize_values([candidate.display_name, candidate.canonical_value, candidate.raw_value, *alias_values]),
        "clonality": _normalize_values([candidate.display_name, candidate.canonical_value, *alias_values]),
        "business_line": _normalize_values([candidate.business_line, candidate.object_type, candidate.display_name]),
        "isotype": [],
        "costim_domain": [],
        "car_t_group": [],
        "descriptive_filter": _normalize_values(descriptive_values),
    }


def _matches_any(value: str, haystacks: Iterable[str], *, exact_only: bool = False) -> bool:
    for haystack in haystacks:
        if value == haystack:
            return True
        if not exact_only and value in haystack:
            return True
    return False


def _normalize_values(values: Iterable[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = normalize_object_alias(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _merge_constraints(
    left: list[AttributeConstraint],
    right: list[AttributeConstraint],
) -> list[AttributeConstraint]:
    merged: list[AttributeConstraint] = []
    seen: set[tuple[str, str, str]] = set()

    for constraint in [*left, *right]:
        key = (
            normalize_object_alias(constraint.attribute),
            normalize_object_alias(constraint.operator),
            normalize_object_alias(constraint.value),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(constraint)

    return merged
