from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.parser_adapter import adapt_parsed_result_to_parser_signals, preprocess_for_parser
from src.ingestion.signal_refinement import refine_parser_signals
from src.memory.models import ClarificationMemory, MemoryContext, MemorySnapshot


def test_adapter_preserves_structured_parser_entity_surface_form_and_offsets():
    payload = {
        "entities": {
            "product_names": [
                {"text": "NPM1", "raw": "npm-1", "start": 14, "end": 19},
            ]
        }
    }

    signals = adapt_parsed_result_to_parser_signals(payload, source_query="tell me about npm-1")
    span = signals.entities.product_names[0]

    assert span.text == "NPM1"
    assert span.raw == "npm-1"
    assert span.start == 14
    assert span.end == 19
    assert span.normalized_value is None


def test_adapter_backfills_offsets_for_legacy_string_entities():
    payload = {
        "entities": {
            "catalog_numbers": ["20001"],
        }
    }

    signals = adapt_parsed_result_to_parser_signals(payload, source_query="datasheet for 20001")
    span = signals.entities.catalog_numbers[0]

    assert span.raw == "20001"
    assert span.text == "20001"
    assert span.start == 14
    assert span.end == 19
    assert span.normalized_value is None


def test_refinement_sets_normalized_value_without_overwriting_surface_form():
    payload = {
        "entities": {
            "product_names": [
                {"text": "NPM1", "raw": "npm-1", "start": 14, "end": 19},
            ]
        }
    }

    parser_signals = adapt_parsed_result_to_parser_signals(payload, source_query="tell me about npm-1")
    refined = refine_parser_signals(parser_signals, normalized_query="tell me about npm-1")
    span = refined.entities.product_names[0]

    assert span.raw == "npm-1"
    assert span.text == "NPM1"
    assert span.start == 14
    assert span.end == 19
    assert span.normalized_value == "NPM1"


def test_adapter_corrects_inaccurate_parser_offsets_against_raw_surface_form():
    payload = {
        "entities": {
            "catalog_numbers": [
                {"text": "20001", "raw": "20001", "start": 24, "end": 29},
            ]
        }
    }

    signals = adapt_parsed_result_to_parser_signals(payload, source_query="Please send datasheet for 20001")
    span = signals.entities.catalog_numbers[0]

    assert span.start == 26
    assert span.end == 31
    assert "Please send datasheet for 20001"[span.start : span.end] == "20001"


def test_preprocess_for_parser_prefers_memory_context_over_direct_anchor_plumbing():
    payload = preprocess_for_parser(
        user_query="The first one sounds right",
        conversation_history=[],
        attachments=[],
        memory_context=MemoryContext(
            snapshot=MemorySnapshot(
                clarification_memory=ClarificationMemory(
                    pending_clarification_type="service_selection",
                    pending_candidate_options=["A", "B"],
                )
            )
        ),
    )

    assert "Type: service_selection" in payload["pending_clarification"]
    assert "1: A" in payload["pending_clarification"]
    assert "2: B" in payload["pending_clarification"]
