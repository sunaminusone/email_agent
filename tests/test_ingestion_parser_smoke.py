from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import OPENAI_API_KEY
from src.ingestion.parser_adapter import adapt_parsed_result_to_parser_signals, invoke_parser


pytestmark = pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY is not configured")


def _assert_span_shape(entity: dict, query: str) -> None:
    assert isinstance(entity, dict)
    assert set(entity.keys()) >= {"text", "raw", "start", "end"}

    text = str(entity["text"] or "").strip()
    raw = str(entity["raw"] or "").strip()
    start = entity["start"]
    end = entity["end"]

    assert text or raw
    assert isinstance(start, int)
    assert isinstance(end, int)

    if start >= 0 and end >= 0:
        assert end >= start
        assert end <= len(query)


def test_parser_returns_structured_product_span_for_alias_lookup():
    query = "tell me about npm-1"
    parsed = invoke_parser(user_query=query, conversation_history=[], attachments=[])

    product_names = parsed["entities"]["product_names"]
    assert product_names
    _assert_span_shape(product_names[0], query)


def test_parser_returns_structured_catalog_span_for_document_request():
    query = "Please send datasheet for 20001"
    parsed = invoke_parser(user_query=query, conversation_history=[], attachments=[])

    catalog_numbers = parsed["entities"]["catalog_numbers"]
    assert catalog_numbers
    _assert_span_shape(catalog_numbers[0], query)


def test_parser_catalog_span_offsets_are_grounded_to_raw_substring():
    query = "Please send datasheet for 20001"
    parsed = invoke_parser(user_query=query, conversation_history=[], attachments=[])

    signals = adapt_parsed_result_to_parser_signals(parsed, source_query=query)
    catalog_numbers = signals.entities.catalog_numbers
    assert catalog_numbers

    entity = catalog_numbers[0]
    extracted = query[entity.start : entity.end]
    assert extracted.lower() == str(entity.raw).lower()


def test_parser_keeps_contextual_follow_up_without_inventing_entity_span():
    query = "Can you send the brochure for that service?"
    parsed = invoke_parser(user_query=query, conversation_history=[], attachments=[])

    entities = parsed["entities"]
    assert entities["product_names"] == []
    assert entities["catalog_numbers"] == []
    assert entities["service_names"] == []
    assert parsed["open_slots"]["referenced_prior_context"] == "that service"
