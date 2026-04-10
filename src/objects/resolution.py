from __future__ import annotations

from collections import Counter

from src.ingestion.models import IngestionBundle
from src.objects.constraint_matching import (
    attach_constraints_to_ambiguous_sets,
    attach_constraints_to_candidates,
    filter_ambiguous_sets_by_constraints,
    filter_candidates_by_constraints,
)
from src.objects.extraction import extract_object_bundle
from src.objects.models import AmbiguousObjectSet, ObjectBundle, ObjectCandidate, ResolvedObjectState


def resolve_objects(ingestion_bundle: IngestionBundle) -> ResolvedObjectState:
    object_bundle = extract_object_bundle(ingestion_bundle)
    return resolve_object_state(ingestion_bundle, object_bundle)


def resolve_object_state(
    ingestion_bundle: IngestionBundle,
    object_bundle: ObjectBundle | None = None,
) -> ResolvedObjectState:
    bundle = object_bundle or extract_object_bundle(ingestion_bundle)
    reference_constraints = ingestion_bundle.turn_signals.reference_signals.attribute_constraints
    current_candidates = [candidate for candidate in bundle.current_candidates if not candidate.is_ambiguous]
    context_candidates = [candidate for candidate in bundle.context_candidates if not candidate.is_ambiguous]
    ambiguous_sets = bundle.ambiguous_sets

    pending_clarification = bool(ingestion_bundle.stateful_anchors.pending_clarification_field)
    can_reuse_context = _can_reuse_context(ingestion_bundle)
    constraints_applied = False
    pending_resolved_candidate: ObjectCandidate | None = None
    constraint_target_mode = _constraint_target_mode(
        ingestion_bundle,
        current_candidates,
        context_candidates,
        ambiguous_sets,
    )

    if reference_constraints and constraint_target_mode != "none":
        if constraint_target_mode == "current_only":
            current_candidates = attach_constraints_to_candidates(current_candidates, reference_constraints)
            filtered_current = filter_candidates_by_constraints(current_candidates, reference_constraints)
            if filtered_current:
                current_candidates = filtered_current
                constraints_applied = True
        else:
            context_candidates = attach_constraints_to_candidates(context_candidates, reference_constraints)
            ambiguous_sets = attach_constraints_to_ambiguous_sets(ambiguous_sets, reference_constraints)
            filtered_context = filter_candidates_by_constraints(context_candidates, reference_constraints)
            filtered_ambiguous_sets, promoted_candidates = filter_ambiguous_sets_by_constraints(
                ambiguous_sets,
                reference_constraints,
            )
            context_candidates = filtered_context
            ambiguous_sets = filtered_ambiguous_sets
            if constraint_target_mode == "pending_only" and len(promoted_candidates) == 1:
                pending_resolved_candidate = promoted_candidates[0]
            for candidate in promoted_candidates:
                context_candidates.append(candidate)
            if filtered_context or filtered_ambiguous_sets or promoted_candidates:
                constraints_applied = True

    primary_object: ObjectCandidate | None = None
    used_stateful_anchor = False
    resolution_reason = ""

    if current_candidates:
        primary_object = max(current_candidates, key=_candidate_score)
        resolution_reason = "Selected the strongest current-turn object candidate."
    elif pending_resolved_candidate is not None:
        primary_object = pending_resolved_candidate
        used_stateful_anchor = True
        resolution_reason = "Resolved the pending clarification to a single object candidate."
    elif not pending_clarification and can_reuse_context and context_candidates:
        primary_object = max(context_candidates, key=_candidate_score)
        used_stateful_anchor = True
        resolution_reason = "Reused contextual object state because the turn depends on prior context."
    elif ambiguous_sets:
        resolution_reason = "No primary object was selected because clarification-worthy ambiguity remains."
    elif reference_constraints and constraint_target_mode != "none" and not constraints_applied:
        resolution_reason = "Reference attribute constraints did not match the targeted contextual candidates."
    elif reference_constraints and constraint_target_mode == "none":
        resolution_reason = "Reference attribute constraints were present, but the turn did not require contextual filtering."
    else:
        resolution_reason = "No object candidates were strong enough to resolve a primary object."

    ambiguous_sets = [_decorate_ambiguous_set(item) for item in ambiguous_sets]

    secondary_objects: list[ObjectCandidate] = []
    seen_keys: set[tuple[str, str, str]] = set()
    if primary_object is not None:
        seen_keys.add(_secondary_key(primary_object))

    for candidate in [*current_candidates, *context_candidates]:
        key = _secondary_key(candidate)
        if key in seen_keys:
            continue
        secondary_objects.append(candidate)
        seen_keys.add(key)

    resolution_confidence = primary_object.confidence if primary_object is not None else 0.0

    return ResolvedObjectState(
        primary_object=primary_object,
        secondary_objects=secondary_objects,
        ambiguous_sets=ambiguous_sets,
        candidate_objects=bundle.all_candidates,
        active_object=primary_object,
        used_stateful_anchor=used_stateful_anchor or (
            primary_object.used_stateful_anchor if primary_object is not None else False
        ),
        resolution_confidence=resolution_confidence,
        resolution_reason=resolution_reason,
    )


def _candidate_score(candidate: ObjectCandidate) -> float:
    score = candidate.confidence

    if candidate.recency == "CURRENT_TURN":
        score += 0.2
    if candidate.source_type == "deterministic":
        score += 0.1
    elif candidate.source_type == "parser":
        score += 0.05
    elif candidate.source_type == "stateful_anchor":
        score -= 0.05
    if candidate.identifier:
        score += 0.05
    if candidate.is_ambiguous:
        score -= 0.25

    return score


def _secondary_key(candidate: ObjectCandidate) -> tuple[str, str, str]:
    return (
        candidate.object_type,
        candidate.identifier_type or "",
        candidate.identifier or candidate.canonical_value or candidate.display_name or candidate.raw_value,
    )


def _can_reuse_context(ingestion_bundle: IngestionBundle) -> bool:
    reference_signals = ingestion_bundle.turn_signals.reference_signals
    return (
        reference_signals.is_context_dependent
        or reference_signals.reference_mode != "none"
        or reference_signals.requires_active_context_for_safe_resolution
    )


def _should_apply_reference_constraints(ingestion_bundle: IngestionBundle) -> bool:
    reference_signals = ingestion_bundle.turn_signals.reference_signals
    return bool(
        reference_signals.attribute_constraints
        and (
            reference_signals.is_context_dependent
            or reference_signals.reference_mode != "none"
            or reference_signals.requires_active_context_for_safe_resolution
            or ingestion_bundle.stateful_anchors.pending_clarification_field
        )
    )


def _constraint_target_mode(
    ingestion_bundle: IngestionBundle,
    current_candidates: list[ObjectCandidate],
    context_candidates: list[ObjectCandidate],
    ambiguous_sets: list[AmbiguousObjectSet],
) -> str:
    if not _should_apply_reference_constraints(ingestion_bundle):
        return "none"

    anchors = ingestion_bundle.stateful_anchors
    reference_signals = ingestion_bundle.turn_signals.reference_signals

    if anchors.pending_clarification_field and ambiguous_sets:
        return "pending_only"
    if context_candidates and (
        reference_signals.is_context_dependent
        or reference_signals.reference_mode != "none"
        or reference_signals.requires_active_context_for_safe_resolution
    ):
        return "context_only"
    if not context_candidates and not ambiguous_sets and current_candidates and not _has_strong_explicit_object(current_candidates):
        return "current_only"
    return "none"


def _has_strong_explicit_object(candidates: list[ObjectCandidate]) -> bool:
    for candidate in candidates:
        if candidate.object_type in {"product", "service"} and (
            candidate.identifier
            or candidate.evidence_spans
            or candidate.confidence >= 0.8
        ):
            return True
    return False


def _decorate_ambiguous_set(ambiguous_set: AmbiguousObjectSet) -> AmbiguousObjectSet:
    ambiguity_kind = _classify_ambiguity_kind(ambiguous_set)
    clarification_focus = _clarification_focus_for_kind(ambiguity_kind)
    suggested_fields = _suggest_disambiguation_fields(ambiguous_set, ambiguity_kind)
    resolution_strategy = _resolution_strategy_for_kind(ambiguity_kind)
    reason = _reason_for_kind(ambiguous_set, ambiguity_kind)
    return ambiguous_set.model_copy(
        update={
            "ambiguity_kind": ambiguity_kind,
            "clarification_focus": clarification_focus,
            "suggested_disambiguation_fields": suggested_fields,
            "resolution_strategy": resolution_strategy,
            "reason": reason,
        }
    )


def _classify_ambiguity_kind(ambiguous_set: AmbiguousObjectSet) -> str:
    alias_kinds: list[str] = []
    for candidate in ambiguous_set.candidates:
        kinds = candidate.metadata.get("matched_alias_kinds", [])
        if isinstance(kinds, list):
            alias_kinds.extend(str(kind) for kind in kinds if kind)

    if not alias_kinds:
        return "generic"

    counts = Counter(alias_kinds)
    if "format_or_size" in counts:
        return "format_or_size"
    if "target_antigen" in counts:
        return "target_antigen"
    if "group_name" in counts:
        return "product_family"
    if "product_type" in counts:
        return "product_type"
    if "construct" in counts or "marker" in counts:
        return "construct"
    if "abbreviation" in counts:
        return "abbreviation"
    if "phrase_fragment" in counts or "page_title_fragment" in counts:
        return "phrase_fragment"
    if "synonym" in counts:
        return "synonym"
    if "canonical_name" in counts:
        return "canonical_name"
    return counts.most_common(1)[0][0]


def _clarification_focus_for_kind(ambiguity_kind: str) -> str:
    mapping = {
        "format_or_size": "product_identity",
        "target_antigen": "product_family",
        "product_family": "product_family",
        "product_type": "product_type",
        "construct": "technical_variant",
        "abbreviation": "service_identity",
        "phrase_fragment": "service_identity",
        "synonym": "catalog_variant",
        "canonical_name": "catalog_variant",
        "generic": "object_identity",
    }
    return mapping.get(ambiguity_kind, "object_identity")


def _resolution_strategy_for_kind(ambiguity_kind: str) -> str:
    mapping = {
        "format_or_size": "clarify_product_before_format",
        "target_antigen": "clarify_product_family",
        "product_family": "clarify_product_family",
        "product_type": "clarify_product_type",
        "construct": "clarify_technical_variant",
        "abbreviation": "clarify_service_identity",
        "phrase_fragment": "clarify_service_identity",
        "synonym": "clarify_catalog_variant",
        "canonical_name": "clarify_catalog_variant",
        "generic": "clarify",
    }
    return mapping.get(ambiguity_kind, "clarify")


def _reason_for_kind(ambiguous_set: AmbiguousObjectSet, ambiguity_kind: str) -> str:
    size = len(ambiguous_set.candidates)
    if ambiguity_kind == "format_or_size":
        return f"The matched phrase refers to a shared format or size across {size} products."
    if ambiguity_kind == "target_antigen":
        return f"The matched phrase refers to a biological target shared by {size} products or product families."
    if ambiguity_kind == "product_family":
        return f"The matched phrase refers to a shared product family label across {size} products."
    if ambiguity_kind == "product_type":
        return f"The matched phrase refers to a broad product type shared by {size} products."
    if ambiguity_kind == "construct":
        return f"The matched phrase refers to a technical construct or marker shared by {size} products."
    if ambiguity_kind == "abbreviation":
        return f"The matched phrase is a service abbreviation that maps to {size} services."
    if ambiguity_kind == "phrase_fragment":
        return f"The matched phrase is a shortened service name fragment shared by {size} services."
    if ambiguity_kind == "synonym":
        return f"The matched synonym maps to {size} catalog products."
    if ambiguity_kind == "canonical_name":
        return f"The matched name maps to {size} catalog variants."
    return ambiguous_set.reason or "Multiple object candidates matched the same phrase."


def _suggest_disambiguation_fields(ambiguous_set: AmbiguousObjectSet, ambiguity_kind: str) -> list[str]:
    preferred = {
        "format_or_size": ["canonical_value", "target_antigen", "business_line"],
        "target_antigen": ["business_line", "clonality", "canonical_value"],
        "product_family": ["canonical_value", "target_antigen", "construct"],
        "product_type": ["canonical_value", "format_or_size", "target_antigen"],
        "construct": ["canonical_value", "target_antigen", "marker"],
        "abbreviation": ["canonical_value", "business_line", "service_line"],
        "phrase_fragment": ["canonical_value", "business_line", "service_line"],
        "synonym": ["clonality", "species_reactivity_text", "application_text"],
        "canonical_name": ["catalog_no", "clonality", "application_text"],
        "generic": ["canonical_value", "catalog_no", "business_line"],
    }.get(ambiguity_kind, ["canonical_value", "catalog_no", "business_line"])

    available = [field for field in preferred if _field_varies_across_candidates(ambiguous_set.candidates, field)]
    if available:
        return available
    fallback = [field for field in ["canonical_value", "catalog_no", "business_line"] if _field_varies_across_candidates(ambiguous_set.candidates, field)]
    return fallback


def _field_varies_across_candidates(candidates: list[ObjectCandidate], field: str) -> bool:
    values: set[str] = set()
    for candidate in candidates:
        value = ""
        if field == "canonical_value":
            value = candidate.canonical_value
        elif field == "catalog_no":
            value = candidate.identifier if candidate.identifier_type == "catalog_no" else ""
        elif field == "business_line":
            value = candidate.business_line
        else:
            value = str(candidate.metadata.get(field, ""))
        value = str(value or "").strip()
        if value:
            values.add(value)
    return len(values) > 1
