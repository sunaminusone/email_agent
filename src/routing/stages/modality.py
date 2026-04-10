from __future__ import annotations

from src.routing.models import DialogueActResult, ModalityDecision, RoutedObjectState
from src.routing.utils import contains_any, normalize_routing_text
from src.routing.vocabulary import EXTERNAL_TERMS, STRUCTURED_TERMS, TECHNICAL_DEEP_DIVE_TERMS, UNSTRUCTURED_TERMS


def resolve_modality(
    query: str,
    object_routing: RoutedObjectState,
    dialogue_act: DialogueActResult,
) -> ModalityDecision:
    text = normalize_routing_text(query or "")
    primary_object = object_routing.primary_object or object_routing.active_object
    object_type = primary_object.object_type if primary_object is not None else "unknown"

    if dialogue_act.act in {"ACKNOWLEDGE", "TERMINATE", "UNKNOWN"}:
        return ModalityDecision(
            primary_modality="unknown",
            confidence=0.7,
            reason="No execution-facing information modality is needed for this dialogue act.",
        )

    if object_type in {"order", "invoice", "shipment", "customer"}:
        supporting = ["structured_lookup"] if contains_any(text, {"document", "summary"}) else []
        return ModalityDecision(
            primary_modality="external_api",
            supporting_modalities=supporting,
            confidence=0.93,
            reason="Operational objects usually require external system access.",
            requires_external_system=True,
            requires_structured_facts=True,
        )

    if object_type == "document":
        return ModalityDecision(
            primary_modality="unstructured_retrieval",
            confidence=0.86,
            reason="Document requests are best handled as unstructured retrieval.",
            requires_unstructured_context=True,
        )

    structured = contains_any(text, STRUCTURED_TERMS)
    unstructured = contains_any(text, UNSTRUCTURED_TERMS)
    external = contains_any(text, EXTERNAL_TERMS)

    if object_type == "product":
        if structured and unstructured:
            return ModalityDecision(
                primary_modality="hybrid",
                supporting_modalities=["structured_lookup", "unstructured_retrieval"],
                confidence=0.9,
                reason="The product request needs both catalog facts and technical context.",
                requires_structured_facts=True,
                requires_unstructured_context=True,
            )
        if unstructured:
            technical = _is_product_technical_question(text)
            return ModalityDecision(
                primary_modality="hybrid" if technical else "unstructured_retrieval",
                supporting_modalities=["structured_lookup"] if technical else [],
                confidence=0.85,
                reason="The product request leans technical and benefits from retrieval over free text.",
                requires_structured_facts=technical,
                requires_unstructured_context=True,
            )
        return ModalityDecision(
            primary_modality="structured_lookup",
            confidence=0.84,
            reason="The product request is primarily fact-oriented.",
            requires_structured_facts=True,
        )

    if object_type in {"service", "scientific_target"}:
        if structured and not unstructured:
            return ModalityDecision(
                primary_modality="structured_lookup",
                confidence=0.72,
                reason="The request focuses on explicit structured service facts.",
                requires_structured_facts=True,
            )
        primary = "hybrid" if structured and unstructured else "unstructured_retrieval"
        return ModalityDecision(
            primary_modality=primary,
            supporting_modalities=["structured_lookup"] if primary == "hybrid" else [],
            confidence=0.86,
            reason="Service and scientific-target requests usually need descriptive retrieval context.",
            requires_structured_facts=primary == "hybrid",
            requires_unstructured_context=True,
        )

    if external:
        return ModalityDecision(
            primary_modality="external_api",
            confidence=0.76,
            reason="The turn mentions operational lookup patterns that imply external systems.",
            requires_external_system=True,
        )

    return ModalityDecision(
        primary_modality="unstructured_retrieval",
        confidence=0.58,
        reason="The request defaults to descriptive retrieval when no stronger modality signal is present.",
        requires_unstructured_context=True,
    )


def _is_product_technical_question(text: str) -> bool:
    return contains_any(
        text,
        TECHNICAL_DEEP_DIVE_TERMS | {"application", "applications", "validation", "validated", "protocol"},
    )
