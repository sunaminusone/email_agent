from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.ingestion.models import IngestionBundle, SelectionResolution
from src.objects.constraint_matching import (
    attach_constraints_to_ambiguous_sets,
    attach_constraints_to_candidates,
    filter_ambiguous_sets_by_constraints,
    filter_candidates_by_constraints,
)
from src.objects.extraction import extract_object_bundle
from src.objects.models import AmbiguousObjectSet, ObjectBundle, ObjectCandidate, ResolvedObjectState

if TYPE_CHECKING:
    from src.memory.models import ScoredObjectRef


@dataclass(frozen=True)
class _ContextEngagement:
    """Aggregated reference + clarification signals for the current turn.

    Stop-gap layer: replaces three near-duplicate predicates that all read
    the same fields off ingestion_bundle.  See
    `project_objects_architecture_backlog.md` — the proper fix is to fold
    these three predicates into a single classifier.
    """

    has_reference_intent: bool
    has_pending_clarification: bool
    has_constraints: bool
    blocks_context_reuse: bool

    @property
    def can_reuse_context(self) -> bool:
        return self.has_reference_intent and not self.blocks_context_reuse

    @property
    def should_apply_constraints(self) -> bool:
        return self.has_constraints and (
            self.has_reference_intent or self.has_pending_clarification
        )


def _build_engagement(
    ingestion_bundle: IngestionBundle,
    trajectory_phase: str | None,
) -> _ContextEngagement:
    reference_signals = ingestion_bundle.turn_signals.reference_signals
    clarification_memory = ingestion_bundle.clarification_memory
    return _ContextEngagement(
        has_reference_intent=(
            reference_signals.is_context_dependent
            or reference_signals.reference_mode != "none"
            or reference_signals.requires_active_context_for_safe_resolution
        ),
        has_pending_clarification=bool(clarification_memory.pending_clarification_type),
        has_constraints=bool(reference_signals.attribute_constraints),
        blocks_context_reuse=trajectory_phase in ("fresh_start", "topic_switch"),
    )


def resolve_objects(
    ingestion_bundle: IngestionBundle,
    *,
    trajectory_phase: str | None = None,
    recent_objects: list[ScoredObjectRef] | None = None,
) -> ResolvedObjectState:
    object_bundle = extract_object_bundle(ingestion_bundle, recent_objects=recent_objects)
    return resolve_object_state(
        ingestion_bundle,
        object_bundle,
        trajectory_phase=trajectory_phase,
    )


def resolve_object_state(
    ingestion_bundle: IngestionBundle,
    object_bundle: ObjectBundle | None = None,
    *,
    trajectory_phase: str | None = None,
) -> ResolvedObjectState:
    bundle = object_bundle or extract_object_bundle(ingestion_bundle)
    reference_constraints = ingestion_bundle.turn_signals.reference_signals.attribute_constraints
    current_candidates = [candidate for candidate in bundle.current_candidates if not candidate.is_ambiguous]
    context_candidates = [candidate for candidate in bundle.context_candidates if not candidate.is_ambiguous]
    ambiguous_sets = bundle.ambiguous_sets

    engagement = _build_engagement(ingestion_bundle, trajectory_phase)
    clarification_memory = ingestion_bundle.clarification_memory
    pending_clarification = engagement.has_pending_clarification
    can_reuse_context = engagement.can_reuse_context
    constraints_applied = False
    pending_resolved_candidate: ObjectCandidate | None = None
    constraint_target_mode = _constraint_target_mode(
        engagement,
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

    # --- LLM selection resolution ---
    # When the parser resolved the user's selection from pending options,
    # use it to pick a candidate from the ambiguous sets.
    selection = ingestion_bundle.turn_signals.parser_signals.selection_resolution
    if (
        pending_clarification
        and pending_resolved_candidate is None
        and selection is not None
        and selection.selection_confidence >= 0.5
        and ambiguous_sets
    ):
        selected = _resolve_selection_from_ambiguous(
            selection,
            ambiguous_sets,
            clarification_memory.pending_candidate_options,
        )
        if selected is not None:
            pending_resolved_candidate = selected
            # Remove the resolved set from ambiguous_sets
            ambiguous_sets = [
                s for s in ambiguous_sets
                if not _ambiguous_set_contains(s, selected)
            ]

    # --- Phase-aware context scoring ---
    if trajectory_phase == "topic_switch":
        context_candidates = [
            candidate.model_copy(update={"confidence": max(0.0, candidate.confidence - 0.15)})
            for candidate in context_candidates
        ]

    # --- Select primary object ---
    primary_object: ObjectCandidate | None = None
    used_memory_context = False
    resolution_reason = ""
    resolution_phase = ""

    if current_candidates:
        primary_object = max(current_candidates, key=_candidate_score)
        resolution_reason = "Selected the strongest current-turn object candidate."
        resolution_phase = "current_turn"
    elif pending_resolved_candidate is not None:
        primary_object = pending_resolved_candidate
        used_memory_context = True
        resolution_reason = "Resolved the pending clarification to a single object candidate."
        resolution_phase = "pending_resolved"
    elif not pending_clarification and can_reuse_context and context_candidates:
        primary_object = max(context_candidates, key=_candidate_score)
        used_memory_context = True
        resolution_reason = "Reused contextual object state because the turn depends on prior context."
        resolution_phase = "context_reuse"
    elif ambiguous_sets:
        resolution_reason = "No primary object was selected because clarification-worthy ambiguity remains."
        resolution_phase = "unresolved"
    elif reference_constraints and constraint_target_mode != "none" and not constraints_applied:
        resolution_reason = "Reference attribute constraints did not match the targeted contextual candidates."
        resolution_phase = "unresolved"
    elif reference_constraints and constraint_target_mode == "none":
        resolution_reason = "Reference attribute constraints were present, but the turn did not require contextual filtering."
        resolution_phase = "unresolved"
    else:
        resolution_reason = "No object candidates were strong enough to resolve a primary object."
        resolution_phase = "unresolved"

    ambiguous_sets = [_decorate_ambiguous_set(item) for item in ambiguous_sets]

    # --- Derive active_object ---
    active_object = _derive_active_object(primary_object, context_candidates)

    # --- Assemble secondary objects ---
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
        active_object=active_object,
        used_memory_context=used_memory_context or (
            primary_object.used_memory_context if primary_object is not None else False
        ),
        resolution_confidence=resolution_confidence,
        resolution_reason=resolution_reason,
        resolution_phase=resolution_phase,
    )


# ---------------------------------------------------------------------------
# Active object derivation
# ---------------------------------------------------------------------------

def _derive_active_object(
    primary_object: ObjectCandidate | None,
    context_candidates: list[ObjectCandidate],
) -> ObjectCandidate | None:
    """Derive active_object independently of primary_object.

    - If primary_object exists, it becomes the active object (current turn takes priority).
    - Otherwise, use the highest-scoring context candidate (already populated from
      recent_objects by context_extractor).
    - If no context candidates, fall back to None.
    """
    if primary_object is not None:
        return primary_object

    if not context_candidates:
        return None

    return max(context_candidates, key=_candidate_score)


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------

def _candidate_score(candidate: ObjectCandidate) -> float:
    score = candidate.confidence

    if candidate.recency == "CURRENT_TURN":
        score += 0.2
    if candidate.source_type == "deterministic":
        score += 0.1
    elif candidate.source_type == "parser":
        score += 0.05
    elif candidate.source_type == "recent_object":
        score -= 0.05
    elif candidate.source_type == "pending_option":
        # Pending options should never compete for primary against
        # current-turn or recent-object candidates.  They are only
        # promotable through selection_resolution or constraint filter.
        score -= 1.0
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


# ---------------------------------------------------------------------------
# Constraint targeting (engagement-driven)
# ---------------------------------------------------------------------------

def _constraint_target_mode(
    engagement: _ContextEngagement,
    current_candidates: list[ObjectCandidate],
    context_candidates: list[ObjectCandidate],
    ambiguous_sets: list[AmbiguousObjectSet],
) -> str:
    if not engagement.should_apply_constraints:
        return "none"
    if engagement.has_pending_clarification and ambiguous_sets:
        return "pending_only"
    if context_candidates and engagement.has_reference_intent:
        return "context_only"
    if (
        not context_candidates
        and not ambiguous_sets
        and current_candidates
        and not _has_strong_explicit_object(current_candidates)
    ):
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


# ---------------------------------------------------------------------------
# Ambiguity classification
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# LLM selection resolution helpers
# ---------------------------------------------------------------------------

def _candidate_label(candidate: ObjectCandidate) -> str:
    """Build the label string that would have been stored in pending_candidate_options."""
    return candidate.display_name or candidate.identifier or candidate.canonical_value


def _resolve_selection_from_ambiguous(
    selection: SelectionResolution,
    ambiguous_sets: list[AmbiguousObjectSet],
    pending_options: list[str],
) -> ObjectCandidate | None:
    """Match the LLM selection result to an ObjectCandidate in ambiguous_sets.

    Strategy (in priority order):
    1. selected_index: if within bounds of pending_options, match the label
       back to a candidate in the ambiguous sets.
    2. selected_value: fuzzy-match against candidate labels.
    """
    # Strategy 1: index-based via pending_options labels
    if selection.selected_index is not None and pending_options:
        idx = selection.selected_index
        if 0 <= idx < len(pending_options):
            target_label = pending_options[idx].strip().lower()
            for ambiguous_set in ambiguous_sets:
                for candidate in ambiguous_set.candidates:
                    if _candidate_label(candidate).strip().lower() == target_label:
                        return candidate.model_copy(
                            update={"is_ambiguous": False, "confidence": max(candidate.confidence, 0.8)},
                        )

    # Strategy 2: value-based match against candidate labels
    if selection.selected_value:
        target = selection.selected_value.strip().lower()
        for ambiguous_set in ambiguous_sets:
            for candidate in ambiguous_set.candidates:
                label = _candidate_label(candidate).strip().lower()
                if label == target or target in label or label in target:
                    return candidate.model_copy(
                        update={"is_ambiguous": False, "confidence": max(candidate.confidence, 0.8)},
                    )

    return None


def _ambiguous_set_contains(ambiguous_set: AmbiguousObjectSet, candidate: ObjectCandidate) -> bool:
    """Check if an ambiguous set contains a candidate (by identity fields)."""
    for c in ambiguous_set.candidates:
        if (
            c.object_type == candidate.object_type
            and c.canonical_value == candidate.canonical_value
            and c.identifier == candidate.identifier
        ):
            return True
    return False
