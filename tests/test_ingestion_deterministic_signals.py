from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.deterministic_signals import (
    detect_document_types,
    extract_deterministic_signals,
    strip_identifier_missing_information,
)
from src.ingestion.models import ParserContext, ParserSignals


def _span_texts(spans):
    return [span.text for span in spans]


def _signal_values(signals):
    return [signal.value for signal in signals]


def _make_parser_signals(*, intent: str = "unknown") -> ParserSignals:
    return ParserSignals(context=ParserContext(primary_intent=intent))


def test_numeric_product_identifier_promotes_to_catalog_number():
    ps = _make_parser_signals(intent="product_inquiry")
    signals = extract_deterministic_signals("Please send datasheet for 32122", parser_signals=ps)

    assert _span_texts(signals.catalog_numbers) == ["32122"]
    assert _span_texts(signals.order_numbers) == []
    assert _signal_values(signals.ambiguous_identifiers) == []


def test_numeric_id_classified_as_order_when_parser_has_order_intent():
    ps = _make_parser_signals(intent="order_support")
    signals = extract_deterministic_signals("check status of 54321", parser_signals=ps)

    assert _span_texts(signals.order_numbers) == ["54321"]
    assert _span_texts(signals.catalog_numbers) == []
    assert _signal_values(signals.ambiguous_identifiers) == []


def test_numeric_id_ambiguous_when_no_parser_signals():
    signals = extract_deterministic_signals("check 54321")

    assert _signal_values(signals.ambiguous_identifiers) == ["54321"]
    assert _span_texts(signals.catalog_numbers) == []
    assert _span_texts(signals.order_numbers) == []


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
