from pathlib import Path
import sys
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.documents import Document

from src.rag.flyer_pricing import (
    _build_flyer_pricing_record,
    _coerce_price,
    _is_pricing_chunk,
    lookup_flyer_pricing,
)


def _make_chunk(metadata: dict, content: str = "") -> Document:
    return Document(page_content=content, metadata=metadata)


def test_is_pricing_chunk_recognizes_pricing_overview_section():
    assert _is_pricing_chunk(_make_chunk({"section_type": "pricing_overview"}))


def test_is_pricing_chunk_recognizes_chunks_with_price_metadata():
    assert _is_pricing_chunk(_make_chunk({"price_usd": "50000"}))
    assert _is_pricing_chunk(_make_chunk({"unit_price_usd": "500"}))
    assert _is_pricing_chunk(_make_chunk({"pricing_tier": "Standard"}))


def test_is_pricing_chunk_rejects_chunks_without_pricing_signal():
    assert not _is_pricing_chunk(_make_chunk({"section_type": "service_overview"}))
    assert not _is_pricing_chunk(_make_chunk({}))


def test_coerce_price_handles_string_int_float_and_commas():
    assert _coerce_price("50000") == 50000
    assert _coerce_price("1,234") == 1234
    assert _coerce_price("99.95") == 99.95
    assert _coerce_price(None) is None
    assert _coerce_price("") is None
    assert _coerce_price("not a number") == "not a number"


def test_build_flyer_pricing_record_normalizes_metadata_into_panel_shape():
    chunk = _make_chunk(
        {
            "service_name": "Custom CAR-T Development",
            "service_line": "car_t_car_nk",
            "business_line": "car-t",
            "section_type": "pricing_overview",
            "section_title": "Pricing - Plan A",
            "price_usd": "50000",
            "price_usd_min": "45000",
            "price_usd_max": "55000",
            "pricing_tier": "Standard",
            "unit": "per sample",
            "unit_price_usd": "500",
            "setup_fee_usd": "2000",
            "price_note": "Volume discounts available",
        },
        content="Plan A delivers full CAR-T service for a flat fee. " * 10,
    )
    record = _build_flyer_pricing_record(chunk)

    assert record["_subsource"] == "service_flyer"
    assert record["service_name"] == "Custom CAR-T Development"
    assert record["business_line"] == "car-t"
    assert record["price"] == 50000
    assert record["price_min"] == 45000
    assert record["price_max"] == 55000
    assert record["currency"] == "USD"
    assert record["pricing_tier"] == "Standard"
    assert record["unit"] == "per sample"
    assert record["unit_price"] == 500
    assert record["setup_fee"] == 2000
    assert record["price_note"] == "Volume discounts available"
    assert record["source_section"] == "Pricing - Plan A"
    # Excerpt is truncated for panel readability.
    assert len(record["source_excerpt"]) <= 240


def test_lookup_flyer_pricing_filters_non_pricing_chunks_and_caps_top_k():
    pricing_chunk = _make_chunk(
        {"section_type": "pricing_overview", "service_name": "X", "price_usd": "100"}
    )
    technical_chunk = _make_chunk({"section_type": "service_overview"})
    second_pricing_chunk = _make_chunk(
        {"section_type": "pricing_overview", "service_name": "Y", "price_usd": "200"}
    )

    class _FakeStore:
        def similarity_search_with_score(self, query, k):
            assert k == 25  # default candidate_pool
            return [
                (technical_chunk, 0.9),
                (pricing_chunk, 0.8),
                (technical_chunk, 0.7),
                (second_pricing_chunk, 0.6),
            ]

    with patch("src.rag.flyer_pricing.get_vectorstore", return_value=_FakeStore()):
        records = lookup_flyer_pricing(query="how much for X")

    assert [r["service_name"] for r in records] == ["X", "Y"]


def test_lookup_flyer_pricing_respects_top_k_cap():
    chunks = [
        _make_chunk(
            {"section_type": "pricing_overview", "service_name": f"S{i}", "price_usd": str(i * 100)}
        )
        for i in range(5)
    ]

    class _FakeStore:
        def similarity_search_with_score(self, query, k):
            return [(chunk, 0.9 - i * 0.01) for i, chunk in enumerate(chunks)]

    with patch("src.rag.flyer_pricing.get_vectorstore", return_value=_FakeStore()):
        records = lookup_flyer_pricing(query="pricing", top_k=2)

    assert len(records) == 2
    assert [r["service_name"] for r in records] == ["S0", "S1"]


def test_lookup_flyer_pricing_returns_empty_on_blank_query():
    assert lookup_flyer_pricing(query="   ") == []


def test_lookup_flyer_pricing_swallows_vectorstore_errors():
    def _raise(*_args, **_kwargs):
        raise RuntimeError("chroma down")

    with patch("src.rag.flyer_pricing.get_vectorstore", side_effect=_raise):
        assert lookup_flyer_pricing(query="anything") == []
