from __future__ import annotations

import re

from src.ingestion.models import (
    AttributeConstraint,
    ParserSignals,
    ReferenceMode,
    ReferenceSignals,
    SourceAttribution,
    StatefulAnchors,
    ValueSignal,
)


_REFERENTIAL_PATTERNS: dict[ReferenceMode, tuple[str, ...]] = {
    "active": (
        "this one",
        "that one",
        "this product",
        "that product",
        "this service",
        "that service",
        "same one",
        "same product",
        "same service",
    ),
    "other": (
        "the other one",
        "the other product",
        "the other service",
        "another one",
        "another product",
        "another service",
    ),
    "first": (
        "the first one",
        "first one",
        "the first product",
        "the first service",
    ),
    "second": (
        "the second one",
        "second one",
        "the second product",
        "the second service",
    ),
    "previous": (
        "the previous one",
        "the previous product",
        "the previous service",
        "previous one",
        "last one",
    ),
    "all": (
        "both of them",
        "all of them",
        "both products",
        "both services",
        "the two of them",
        "those two",
    ),
    "none": (),
}
_PRONOUN_PATTERNS = ("it", "its", "it's", "they", "them", "this", "that", "these", "those")
_ATTRIBUTE_PATTERN = re.compile(
    r"\b(the|this|that)\s+([a-z0-9][a-z0-9_-]*(?:\s+[a-z0-9][a-z0-9_-]*){0,3})\s+one\b",
    re.IGNORECASE,
)
_PRONOUN_REGEX = re.compile(r"\b(?:it|its|they|them|this|that|these|those)\b", re.IGNORECASE)
_FORMAT_OR_SIZE_REGEX = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ul|ml|l|mg|ug|g)\b", re.IGNORECASE)
_SPECIES_TERMS = ("rabbit", "mouse", "human", "rat")
_APPLICATION_OR_VALIDATION_TERMS = (
    "ihc-validated",
    "ihc",
    "wb",
    "western blot",
    "elisa",
    "flow",
    "flow cytometry",
    "facs",
    "validated",
)
_CLONALITY_TERMS = ("monoclonal", "polyclonal")
_REFERENTIAL_ATTRIBUTE_BLACKLIST = {
    "first",
    "second",
    "other",
    "previous",
    "same",
    "last",
}


def _normalize_text(value: str) -> str:
    lowered = str(value or "").strip().lower()
    lowered = lowered.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", lowered)


def _reference_attribution() -> SourceAttribution:
    return SourceAttribution(
        source_type="deterministic",
        recency="CURRENT_TURN",
        confidence=0.8,
        source_label="ingestion.reference",
    )


def _build_attribute_constraint(attribute: str, value: str, raw: str) -> AttributeConstraint:
    return AttributeConstraint(
        attribute=attribute,
        operator="equals",
        value=value,
        raw=raw,
        attribution=_reference_attribution(),
    )


def detect_reference_mode(query: str) -> ReferenceMode:
    normalized_query = f" {_normalize_text(query)} "
    for mode in ("other", "all", "first", "second", "previous", "active"):
        if any(pattern in normalized_query for pattern in _REFERENTIAL_PATTERNS[mode]):
            return mode
    if detect_pronoun_reference(query):
        return "active"
    return "none"


def detect_pronoun_reference(query: str) -> bool:
    normalized_query = _normalize_text(query)
    return bool(_PRONOUN_REGEX.search(normalized_query))


def detect_context_dependence(
    query: str,
    parser_signals: ParserSignals,
    reference_mode: ReferenceMode,
) -> bool:
    if reference_mode != "none" or detect_pronoun_reference(query):
        return True
    return bool(parser_signals.open_slots.referenced_prior_context)


def _classify_reference_descriptor(descriptor: str, *, raw: str) -> list[AttributeConstraint]:
    normalized = " ".join(str(descriptor or "").strip().lower().split())
    constraints: list[AttributeConstraint] = []

    size_matches = list(dict.fromkeys(match.group(0).lower().replace(" ", "") for match in _FORMAT_OR_SIZE_REGEX.finditer(normalized)))
    for value in size_matches:
        constraints.append(_build_attribute_constraint("format_or_size", value, raw))

    for term in _SPECIES_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", normalized):
            constraints.append(_build_attribute_constraint("species", term, raw))

    consumed_spans: list[tuple[int, int]] = []
    for term in sorted(_APPLICATION_OR_VALIDATION_TERMS, key=len, reverse=True):
        for match in re.finditer(rf"\b{re.escape(term)}\b", normalized):
            start, end = match.span()
            if any(not (end <= existing_start or start >= existing_end) for existing_start, existing_end in consumed_spans):
                continue
            consumed_spans.append((start, end))
            constraints.append(_build_attribute_constraint("application_or_validation", term, raw))

    for term in _CLONALITY_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", normalized):
            constraints.append(_build_attribute_constraint("clonality", term, raw))

    if constraints:
        seen: set[tuple[str, str]] = set()
        deduped: list[AttributeConstraint] = []
        for constraint in constraints:
            key = (constraint.attribute, constraint.value)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(constraint)
        return deduped

    return [_build_attribute_constraint("descriptive_filter", normalized, raw)]


def extract_reference_attribute_constraints(query: str) -> list[AttributeConstraint]:
    constraints: list[AttributeConstraint] = []
    for match in _ATTRIBUTE_PATTERN.finditer(query):
        value = " ".join(match.group(2).strip().lower().split())
        if value in _REFERENTIAL_ATTRIBUTE_BLACKLIST:
            continue
        constraints.extend(_classify_reference_descriptor(value, raw=match.group(0)))
    return constraints


def requires_active_context_for_safe_resolution(
    reference_mode: ReferenceMode,
    is_context_dependent: bool,
    stateful_anchors: StatefulAnchors,
) -> bool:
    if not is_context_dependent:
        return False
    has_active_context = bool(
        stateful_anchors.active_entity_identifier
        or stateful_anchors.active_entity_display_name
        or stateful_anchors.active_business_line
    )
    has_candidate_context = bool(stateful_anchors.pending_candidate_options)
    if reference_mode == "active":
        return not has_active_context
    if reference_mode in {"other", "first", "second", "previous", "all"}:
        return not (has_active_context or has_candidate_context)
    return not has_active_context


def extract_reference_signals(
    query: str,
    parser_signals: ParserSignals,
    stateful_anchors: StatefulAnchors | None = None,
) -> ReferenceSignals:
    anchors = stateful_anchors or StatefulAnchors()
    reference_mode = detect_reference_mode(query)
    is_context_dependent = detect_context_dependence(query, parser_signals, reference_mode)
    referenced_prior_context = None
    if parser_signals.open_slots.referenced_prior_context:
        raw_reference = str(parser_signals.open_slots.referenced_prior_context).strip()
        referenced_prior_context = ValueSignal(
            value=raw_reference,
            raw=raw_reference,
            normalized_value=raw_reference,
            attribution=SourceAttribution(
                source_type="parser",
                recency="CURRENT_TURN",
                confidence=1.0,
                source_label="parser.open_slots.referenced_prior_context",
            ),
        )

    return ReferenceSignals(
        is_context_dependent=is_context_dependent,
        reference_mode=reference_mode,
        referenced_prior_context=referenced_prior_context,
        attribute_constraints=extract_reference_attribute_constraints(query),
        requires_active_context_for_safe_resolution=requires_active_context_for_safe_resolution(
            reference_mode,
            is_context_dependent,
            anchors,
        ),
    )
