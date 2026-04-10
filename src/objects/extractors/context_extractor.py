from __future__ import annotations

from src.ingestion.models import IngestionBundle
from src.objects.constraint_matching import attach_constraints_to_ambiguous_sets, attach_constraints_to_candidates
from src.objects.models import AmbiguousObjectSet, ExtractorOutput, ObjectCandidate


def extract_context_candidates(ingestion_bundle: IngestionBundle) -> ExtractorOutput:
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

    active_kind = _coerce_object_type(anchors.active_entity_kind.value if anchors.active_entity_kind else "")
    active_identifier = anchors.active_entity_identifier.value if anchors.active_entity_identifier else ""
    active_display_name = anchors.active_entity_display_name.value if anchors.active_entity_display_name else ""
    business_line = anchors.active_business_line.value if anchors.active_business_line else ""

    if should_reuse_context and (active_identifier or active_display_name):
        candidates.append(
            ObjectCandidate(
                object_type=active_kind,
                raw_value=active_display_name or active_identifier,
                canonical_value=active_display_name or active_identifier,
                display_name=active_display_name or active_identifier,
                identifier=active_identifier,
                identifier_type="stateful_anchor",
                business_line=business_line,
                confidence=0.6 if reference_signals.is_context_dependent else 0.45,
                recency="CONTEXTUAL",
                source_type="stateful_anchor",
                attribute_constraints=reference_constraints,
                used_stateful_anchor=True,
                metadata={
                    "active_route": anchors.active_route,
                    "reference_mode": reference_signals.reference_mode,
                },
            )
        )

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


def _coerce_object_type(value: str) -> str:
    normalized = (value or "").strip().lower()
    allowed = {
        "product",
        "service",
        "order",
        "invoice",
        "shipment",
        "document",
        "customer",
        "scientific_target",
    }
    return normalized if normalized in allowed else "unknown"


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
