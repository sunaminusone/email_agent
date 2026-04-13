from __future__ import annotations

from typing import TYPE_CHECKING

from src.ingestion.models import IngestionBundle
from src.memory.models import SALIENCE_HIGH
from src.objects.constraint_matching import attach_constraints_to_ambiguous_sets, attach_constraints_to_candidates
from src.objects.models import AmbiguousObjectSet, ExtractorOutput, ObjectCandidate

if TYPE_CHECKING:
    from src.memory.models import ScoredObjectRef


def extract_context_candidates(
    ingestion_bundle: IngestionBundle,
    recent_objects: list[ScoredObjectRef] | None = None,
) -> ExtractorOutput:
    anchors = ingestion_bundle.stateful_anchors
    reference_signals = ingestion_bundle.turn_signals.reference_signals
    reference_constraints = reference_signals.attribute_constraints

    candidates: list[ObjectCandidate] = []
    ambiguous_sets: list[AmbiguousObjectSet] = []

    should_reuse_context = (
        reference_signals.is_context_dependent
        or reference_signals.requires_active_context_for_safe_resolution
        or reference_signals.reference_mode != "none"
        or bool(anchors.pending_clarification_field)
    )

    # --- Context candidates from memory recent_objects ---
    if recent_objects:
        if should_reuse_context:
            # Full injection: all recent objects as context candidates
            base = 0.6 if reference_signals.is_context_dependent else 0.45
            for scored_ref in recent_objects:
                ref = scored_ref.object_ref
                if not (ref.identifier or ref.display_name):
                    continue
                salience_factor = min(scored_ref.salience / SALIENCE_HIGH, 1.0)
                candidates.append(_scored_ref_to_candidate(
                    scored_ref,
                    confidence=round(base * salience_factor, 4),
                    reference_constraints=reference_constraints,
                    active_route=anchors.active_route,
                    reference_mode=reference_signals.reference_mode,
                ))
        else:
            # Background injection: only top-1 at low confidence for active_object derivation
            top = recent_objects[0]
            ref = top.object_ref
            if ref.identifier or ref.display_name:
                salience_factor = min(top.salience / SALIENCE_HIGH, 1.0)
                candidates.append(_scored_ref_to_candidate(
                    top,
                    confidence=round(0.3 * salience_factor, 4),
                    reference_constraints=[],
                    active_route=anchors.active_route,
                    reference_mode="none",
                ))

    # --- Pending clarification options (still from stateful_anchors) ---
    if anchors.pending_clarification_field and anchors.pending_candidate_options:
        option_candidates = [
            ObjectCandidate(
                object_type=_infer_pending_object_type(anchors.pending_clarification_field),
                raw_value=option,
                canonical_value=option,
                display_name=option,
                identifier=option if anchors.pending_clarification_field.endswith("_selection") else "",
                identifier_type="pending_option" if anchors.pending_clarification_field.endswith("_selection") else "",
                confidence=0.35,
                recency="CONTEXTUAL",
                source_type="stateful_anchor",
                attribute_constraints=reference_constraints,
                is_ambiguous=True,
                used_stateful_anchor=True,
                metadata={"pending_field": anchors.pending_clarification_field},
            )
            for option in anchors.pending_candidate_options
            if option
        ]
        if option_candidates:
            ambiguous_sets.append(
                AmbiguousObjectSet(
                    object_type=_infer_pending_object_type(anchors.pending_clarification_field),
                    query_value=anchors.pending_identifier or anchors.pending_clarification_field,
                    candidates=option_candidates,
                    resolution_strategy="clarify",
                    reason="Pending clarification options are still active in stateful anchors.",
                    attribute_constraints=reference_constraints,
                )
            )

    return ExtractorOutput(
        candidates=attach_constraints_to_candidates(candidates, reference_constraints),
        ambiguous_sets=attach_constraints_to_ambiguous_sets(ambiguous_sets, reference_constraints),
    )


def _scored_ref_to_candidate(
    scored_ref: ScoredObjectRef,
    *,
    confidence: float,
    reference_constraints: list,
    active_route: str,
    reference_mode: str,
) -> ObjectCandidate:
    ref = scored_ref.object_ref
    return ObjectCandidate(
        object_type=ref.object_type,
        raw_value=ref.display_name or ref.identifier,
        canonical_value=ref.display_name or ref.identifier,
        display_name=ref.display_name or ref.identifier,
        identifier=ref.identifier,
        identifier_type=ref.identifier_type or "memory",
        business_line=ref.business_line,
        confidence=confidence,
        recency="CONTEXTUAL",
        source_type="stateful_anchor",
        attribute_constraints=reference_constraints,
        used_stateful_anchor=True,
        metadata={
            "active_route": active_route,
            "reference_mode": reference_mode,
            "source": "memory_recent_objects",
            "salience": scored_ref.salience,
        },
    )


def _infer_pending_object_type(field_name: str) -> str:
    normalized = (field_name or "").strip().lower()
    if "product" in normalized:
        return "product"
    if "service" in normalized:
        return "service"
    if "order" in normalized:
        return "order"
    if "invoice" in normalized:
        return "invoice"
    if "shipment" in normalized or "delivery" in normalized:
        return "shipment"
    if "document" in normalized:
        return "document"
    if "customer" in normalized or "company" in normalized:
        return "customer"
    return "unknown"
