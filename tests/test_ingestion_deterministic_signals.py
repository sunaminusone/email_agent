from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.deterministic_signals import (
    classify_identifier_candidates,
    detect_document_types,
    extract_deterministic_signals,
    strip_identifier_missing_information,
)


def _span_texts(spans):
    return [span.text for span in spans]


def _signal_values(signals):
    return [signal.value for signal in signals]


def test_numeric_product_identifier_promotes_to_catalog_number():
    signals = extract_deterministic_signals("Please send datasheet for 32122")

    assert _span_texts(signals.catalog_numbers) == ["32122"]
    assert _span_texts(signals.order_numbers) == []
    assert _signal_values(signals.ambiguous_identifiers) == []


def test_weak_product_reference_sets_product_context():
    signals = extract_deterministic_signals("datasheet for abc-123")

    assert signals.product_context is True
    assert _span_texts(signals.catalog_numbers) == ["ABC-123"]


def test_weak_invoice_reference_sets_invoice_context():
    signals = extract_deterministic_signals("invoice abc123")

    assert signals.invoice_context is True
    assert _span_texts(signals.invoice_numbers) == ["ABC123"]


def test_weak_order_reference_sets_order_context():
    signals = extract_deterministic_signals("tracking 54321")

    assert signals.order_context is True
    assert _span_texts(signals.order_numbers) == ["54321"]


def test_technical_context_recognizes_legacy_synonyms():
    wb_signals = extract_deterministic_signals("Need WB validation details")
    ihc_signals = extract_deterministic_signals("Need immunohistochemistry support")
    facs_signals = extract_deterministic_signals("Do you have FACS data?")

    assert wb_signals.technical_context is True
    assert ihc_signals.technical_context is True
    assert facs_signals.technical_context is True


def test_strip_identifier_missing_information_matches_legacy_behavior():
    cleaned = strip_identifier_missing_information(
        [
            "Please provide the catalog number.",
            "Need target information.",
            "What is your timeline?",
            "Share the alias if available.",
        ]
    )

    assert cleaned == ["What is your timeline?"]


def test_detect_document_types_matches_expected_output():
    assert detect_document_types("Please send the datasheet and COA") == ["datasheet", "coa"]


def test_classify_identifier_candidates_exposes_ingestion_signal_summary():
    signals = classify_identifier_candidates("tracking 54321")

    assert signals == {
        "catalog_numbers": [],
        "order_numbers": ["54321"],
        "ambiguous_identifiers": [],
        "product_context": False,
        "invoice_context": False,
        "order_context": True,
        "documentation_context": False,
        "pricing_context": False,
        "timeline_context": False,
    }
