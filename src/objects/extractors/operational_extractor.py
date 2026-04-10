from __future__ import annotations

from src.ingestion.models import EntitySpan, IngestionBundle, ValueSignal
from src.objects.models import ExtractorOutput, ObjectCandidate


def extract_operational_candidates(ingestion_bundle: IngestionBundle) -> ExtractorOutput:
    parser_entities = ingestion_bundle.turn_signals.parser_signals.entities
    parser_flags = ingestion_bundle.turn_signals.parser_signals.request_flags
    deterministic = ingestion_bundle.turn_signals.deterministic_signals

    candidates: list[ObjectCandidate] = []

    candidates.extend(
        _build_identifier_candidates(
            parser_entities.order_numbers,
            object_type="order",
            identifier_type="order_number",
            source_type="parser",
            confidence=0.93,
        )
    )
    candidates.extend(
        _build_identifier_candidates(
            deterministic.order_numbers,
            object_type="order",
            identifier_type="order_number",
            source_type="deterministic",
            confidence=0.98,
        )
    )
    candidates.extend(
        _build_identifier_candidates(
            parser_entities.invoice_numbers,
            object_type="invoice",
            identifier_type="invoice_number",
            source_type="parser",
            confidence=0.93,
        )
    )
    candidates.extend(
        _build_identifier_candidates(
            deterministic.invoice_numbers,
            object_type="invoice",
            identifier_type="invoice_number",
            source_type="deterministic",
            confidence=0.98,
        )
    )
    candidates.extend(
        _build_text_candidates(
            parser_entities.document_names,
            object_type="document",
            identifier_type="document_name",
            source_type="parser",
            confidence=0.72,
        )
    )
    candidates.extend(
        _build_text_candidates(
            parser_entities.customer_names,
            object_type="customer",
            identifier_type="customer_name",
            source_type="parser",
            confidence=0.7,
        )
    )
    candidates.extend(
        _build_text_candidates(
            parser_entities.company_names,
            object_type="customer",
            identifier_type="company_name",
            source_type="parser",
            confidence=0.66,
        )
    )
    candidates.extend(
        _build_value_signal_candidates(
            deterministic.document_types,
            object_type="document",
            identifier_type="document_type",
            source_type="deterministic",
            confidence=0.78,
        )
    )

    if parser_flags.needs_shipping_info:
        shipment_evidence = [*parser_entities.order_numbers, *deterministic.order_numbers]
        for span in shipment_evidence:
            candidates.append(
                ObjectCandidate(
                    object_type="shipment",
                    raw_value=span.text,
                    canonical_value=span.text,
                    display_name=span.text,
                    identifier=span.text,
                    identifier_type="related_order_number",
                    confidence=0.58,
                    recency="CURRENT_TURN",
                    source_type=span.attribution.source_type,
                    evidence_spans=[span],
                    metadata={"derived_from": "shipping_request"},
                )
            )

    return ExtractorOutput(candidates=candidates)


def _build_identifier_candidates(
    spans: list[EntitySpan],
    *,
    object_type: str,
    identifier_type: str,
    source_type: str,
    confidence: float,
) -> list[ObjectCandidate]:
    return [
        ObjectCandidate(
            object_type=object_type,
            raw_value=span.text,
            canonical_value=span.text,
            display_name=span.text,
            identifier=span.text,
            identifier_type=identifier_type,
            confidence=confidence,
            recency="CURRENT_TURN",
            source_type=source_type,
            evidence_spans=[span],
        )
        for span in spans
        if span.text
    ]


def _build_text_candidates(
    spans: list[EntitySpan],
    *,
    object_type: str,
    identifier_type: str,
    source_type: str,
    confidence: float,
) -> list[ObjectCandidate]:
    return [
        ObjectCandidate(
            object_type=object_type,
            raw_value=span.text,
            canonical_value=span.normalized_value or span.text,
            display_name=span.text,
            identifier=span.text,
            identifier_type=identifier_type,
            confidence=confidence,
            recency="CURRENT_TURN",
            source_type=source_type,
            evidence_spans=[span],
        )
        for span in spans
        if span.text
    ]


def _build_value_signal_candidates(
    signals: list[ValueSignal],
    *,
    object_type: str,
    identifier_type: str,
    source_type: str,
    confidence: float,
) -> list[ObjectCandidate]:
    return [
        ObjectCandidate(
            object_type=object_type,
            raw_value=signal.raw or signal.value,
            canonical_value=signal.normalized_value or signal.value,
            display_name=signal.value,
            identifier=signal.value,
            identifier_type=identifier_type,
            confidence=confidence,
            recency=signal.attribution.recency,
            source_type=source_type,
            metadata={"source_label": signal.attribution.source_label},
        )
        for signal in signals
        if signal.value
    ]
