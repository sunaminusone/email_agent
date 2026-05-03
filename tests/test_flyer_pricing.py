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
    _detect_preferred_services,
    _focused_pricing_search,
    _is_pricing_chunk,
    _rerank_by_preferred_service,
    _select_companion_chunk,
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
            # In Chroma metadata, `service_line` is the human-readable label
            # and `business_line` is the slug — opposite of what the names
            # suggest. The flyer record prefers the readable form.
            "service_line": "CAR-T/CAR-NK Development",
            "business_line": "car_t_car_nk",
            "section_type": "service_phase",
            "section_title": "Plan A - Phase III",
            "plan_name": "Plan A",
            "phase_name": "Phase III",
            "phase_role": "main_phase",
            "optional": "no",
            "duration_weeks": 4,
            "price_usd": "7000",
            "price_usd_min": "6500",
            "price_usd_max": "7500",
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
    assert record["business_line"] == "CAR-T/CAR-NK Development"
    assert record["plan_name"] == "Plan A"
    assert record["phase_name"] == "Phase III"
    assert record["phase_role"] == "main_phase"
    assert record["optional"] == "no"
    assert record["duration_weeks"] == 4
    assert record["price"] == 7000
    assert record["price_min"] == 6500
    assert record["price_max"] == 7500
    assert record["currency"] == "USD"
    assert record["pricing_tier"] == "Standard"
    assert record["unit"] == "per sample"
    assert record["unit_price"] == 500
    assert record["setup_fee"] == 2000
    assert record["price_note"] == "Volume discounts available"
    assert record["source_section"] == "Plan A - Phase III"
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
            assert k == 35  # default candidate_pool — bumped from 25 so
            # benchmark / yield-range companion chunks (which can land at
            # rank ~25 for "how much" queries) stay inside the pool.
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


def test_detect_preferred_services_substring_keywords():
    # Returns canonical (case-correct) service_name strings so the
    # value can be used directly as a Chroma metadata filter.
    assert _detect_preferred_services(
        "How much does 100 mg recombinant protein expression in HEK293 cost?"
    ) == {"Mammalian Protein Expression"}
    assert _detect_preferred_services("BL21 expression for 50 mg") == {
        "E. coli Protein Expression"
    }
    assert _detect_preferred_services("Pichia yeast service quote") == {
        "Yeast Protein Expression"
    }
    assert _detect_preferred_services("baculovirus pricing") == {
        "Baculovirus Protein Expression"
    }


def test_detect_preferred_services_word_boundary_keywords():
    # "cho" matches as a word but not inside "echo" or "psycho".
    assert _detect_preferred_services("expression in CHO cells") == {
        "Mammalian Protein Expression"
    }
    assert _detect_preferred_services("just an echo in the ravine") == set()
    # Sf9 is a word-boundary token to avoid incidental substring hits.
    assert _detect_preferred_services("Sf9 packaging cost") == {
        "Baculovirus Protein Expression"
    }


def test_detect_preferred_services_returns_empty_when_no_signal():
    assert _detect_preferred_services("how much for protein expression?") == set()


def test_rerank_by_preferred_service_moves_matching_service_to_front():
    yeast = _make_chunk({"service_name": "Yeast Protein Expression"})
    mammalian = _make_chunk({"service_name": "Mammalian Protein Expression"})
    ecoli = _make_chunk({"service_name": "E. coli Protein Expression"})
    hits = [(yeast, 0.9), (mammalian, 0.8), (ecoli, 0.7)]

    reranked = _rerank_by_preferred_service(hits, {"Mammalian Protein Expression"})

    # Mammalian moves to front; relative order of others is preserved.
    assert [(c.metadata or {}).get("service_name") for c, _ in reranked] == [
        "Mammalian Protein Expression",
        "Yeast Protein Expression",
        "E. coli Protein Expression",
    ]


def test_rerank_by_preferred_service_no_op_without_preferred_set():
    a = _make_chunk({"service_name": "A"})
    b = _make_chunk({"service_name": "B"})
    hits = [(a, 0.9), (b, 0.8)]
    assert _rerank_by_preferred_service(hits, set()) == hits


def test_select_companion_chunk_prefers_benchmark_over_other_types():
    yield_chunk = _make_chunk(
        {
            "service_name": "Mammalian Protein Expression",
            "section_type": "benchmark",
            "section_title": "Mammalian Expression Yield Range",
        }
    )
    workflow_chunk = _make_chunk(
        {
            "service_name": "Mammalian Protein Expression",
            "section_type": "workflow_overview",
            "section_title": "Mammalian Protein Expression Workflow",
        }
    )
    # Workflow has higher similarity but benchmark wins on priority.
    hits = [(workflow_chunk, 0.7), (yield_chunk, 0.9)]
    selected = _select_companion_chunk(
        service_name="Mammalian Protein Expression",
        ranked_hits=hits,
        primary_keys=set(),
    )
    assert selected is yield_chunk


def test_select_companion_chunk_falls_through_priority_when_top_tier_missing():
    workflow_chunk = _make_chunk(
        {
            "service_name": "Yeast Protein Expression",
            "section_type": "workflow_overview",
            "section_title": "Yeast Workflow",
        }
    )
    plan_chunk = _make_chunk(
        {
            "service_name": "Yeast Protein Expression",
            "section_type": "plan_summary",
            "section_title": "Yeast Plan Summary",
        }
    )
    hits = [(workflow_chunk, 0.9), (plan_chunk, 0.8)]
    # No benchmark/phase_overview present → plan_summary beats workflow_overview.
    selected = _select_companion_chunk(
        service_name="Yeast Protein Expression",
        ranked_hits=hits,
        primary_keys=set(),
    )
    assert selected is plan_chunk


def test_select_companion_chunk_skips_chunk_already_used_as_primary():
    used = _make_chunk(
        {
            "service_name": "X",
            "section_type": "benchmark",
            "section_title": "Yield",
        }
    )
    selected = _select_companion_chunk(
        service_name="X",
        ranked_hits=[(used, 0.9)],
        primary_keys={("X", "Yield")},
    )
    assert selected is None


def test_select_companion_chunk_returns_none_when_no_eligible_section_type():
    only_marketing = _make_chunk(
        {
            "service_name": "X",
            "section_type": "service_overview",
            "section_title": "Why Choose X",
        }
    )
    selected = _select_companion_chunk(
        service_name="X",
        ranked_hits=[(only_marketing, 0.9)],
        primary_keys=set(),
    )
    assert selected is None


def test_lookup_flyer_pricing_attaches_companion_per_service_with_primary():
    mammalian_pricing = _make_chunk(
        {
            "service_name": "Mammalian Protein Expression",
            "section_type": "pricing_overview",
            "section_title": "Service Plans and Prices",
        },
        content="Phase I $2000, Phase II $2500, Phase III $3500. Total $8000.",
    )
    mammalian_yield = _make_chunk(
        {
            "service_name": "Mammalian Protein Expression",
            "section_type": "benchmark",
            "section_title": "Mammalian Expression Yield Range",
        },
        content="Yields ~200 micrograms to 25 mg/L, average 3 mg/L.",
    )
    yeast_pricing = _make_chunk(
        {
            "service_name": "Yeast Protein Expression",
            "section_type": "pricing_overview",
            "section_title": "Yeast Plans and Prices",
        }
    )

    class _FakeStore:
        def similarity_search_with_score(self, query, k):
            return [
                (yeast_pricing, 0.9),
                (mammalian_pricing, 0.8),
                (mammalian_yield, 0.7),
            ]

    with patch("src.rag.flyer_pricing.get_vectorstore", return_value=_FakeStore()):
        records = lookup_flyer_pricing(
            query="How much does 100 mg recombinant protein expression in HEK293 cost?"
        )

    # Mammalian rerank fires (HEK293 keyword) → mammalian primary first;
    # yeast still fills second primary slot. One companion attaches to
    # mammalian (yield range); yeast has no eligible companion in pool.
    roles = [(r["service_name"], r.get("source_section"), r["_chunk_role"]) for r in records]
    assert roles == [
        ("Mammalian Protein Expression", "Service Plans and Prices", "primary"),
        ("Yeast Protein Expression", "Yeast Plans and Prices", "primary"),
        ("Mammalian Protein Expression", "Mammalian Expression Yield Range", "companion"),
    ]


def test_lookup_flyer_pricing_emits_no_companion_when_none_eligible():
    pricing_only = _make_chunk(
        {
            "service_name": "X",
            "section_type": "pricing_overview",
            "section_title": "Plans",
            "price_usd": "100",
        }
    )

    class _FakeStore:
        def similarity_search_with_score(self, query, k, filter=None):
            return [(pricing_only, 0.9)]

    with patch("src.rag.flyer_pricing.get_vectorstore", return_value=_FakeStore()):
        records = lookup_flyer_pricing(query="how much for X")
    assert len(records) == 1
    assert records[0]["_chunk_role"] == "primary"


def test_focused_pricing_search_returns_only_pricing_chunks():
    pricing = _make_chunk(
        {"service_name": "Mammalian Protein Expression",
         "section_type": "pricing_overview", "section_title": "Plans"}
    )
    non_pricing = _make_chunk(
        {"service_name": "Mammalian Protein Expression",
         "section_type": "service_overview", "section_title": "Overview"}
    )

    class _FakeStore:
        def __init__(self):
            self.last_filter = None

        def similarity_search_with_score(self, query, k, filter=None):
            self.last_filter = filter
            return [(non_pricing, 0.7), (pricing, 0.9)]

    store = _FakeStore()
    out = _focused_pricing_search(
        store=store, query="cost", service_name="Mammalian Protein Expression",
    )
    assert store.last_filter == {"service_name": "Mammalian Protein Expression"}
    assert [c.metadata["section_title"] for c, _ in out] == ["Plans"]


def test_focused_pricing_search_swallows_filter_errors():
    class _FakeStore:
        def similarity_search_with_score(self, query, k, filter=None):
            raise RuntimeError("filter unsupported")

    out = _focused_pricing_search(
        store=_FakeStore(), query="x", service_name="Anything",
    )
    assert out == []


def test_lookup_flyer_pricing_augments_pool_with_focused_pricing_for_each_preferred_service():
    """The Q6 regression: multi-platform comparison query whose
    unfiltered pool surfaced zero pricing chunks for Mammalian /
    E. coli. Focused per-service search must rescue them."""
    yeast_pricing = _make_chunk(
        {"service_name": "Yeast Protein Expression",
         "section_type": "pricing_overview", "section_title": "Yeast Plans"}
    )
    mammalian_non_pricing = _make_chunk(
        {"service_name": "Mammalian Protein Expression",
         "section_type": "service_overview", "section_title": "Overview"}
    )
    mammalian_pricing_focused = _make_chunk(
        {"service_name": "Mammalian Protein Expression",
         "section_type": "pricing_overview", "section_title": "Mammalian Plans"}
    )
    ecoli_pricing_focused = _make_chunk(
        {"service_name": "E. coli Protein Expression",
         "section_type": "pricing_overview", "section_title": "E. coli Plans"}
    )

    class _FakeStore:
        def similarity_search_with_score(self, query, k, filter=None):
            if filter is None:
                # Unfiltered candidate pool: dominated by yeast, with one
                # non-pricing mammalian chunk and zero e. coli.
                return [(yeast_pricing, 0.9), (mammalian_non_pricing, 0.85)]
            sn = filter.get("service_name")
            if sn == "Mammalian Protein Expression":
                return [(mammalian_pricing_focused, 0.95)]
            if sn == "E. coli Protein Expression":
                return [(ecoli_pricing_focused, 0.95)]
            return []

    with patch("src.rag.flyer_pricing.get_vectorstore", return_value=_FakeStore()):
        records = lookup_flyer_pricing(
            query="expression in HEK293 vs CHO vs BL21"
        )

    # Both preferred-service pricing chunks rescued; primaries fill
    # ahead of the yeast hit from the unfiltered pool.
    primary_services = [
        r["service_name"] for r in records if r["_chunk_role"] == "primary"
    ]
    assert "Mammalian Protein Expression" in primary_services
    assert "E. coli Protein Expression" in primary_services


def test_lookup_flyer_pricing_dedupes_focused_hits_already_in_pool():
    shared_pricing = _make_chunk(
        {"service_name": "Mammalian Protein Expression",
         "section_type": "pricing_overview", "section_title": "Plans"}
    )

    class _FakeStore:
        def __init__(self):
            self.focused_calls = 0

        def similarity_search_with_score(self, query, k, filter=None):
            if filter is None:
                return [(shared_pricing, 0.9)]
            self.focused_calls += 1
            return [(shared_pricing, 0.95)]

    store = _FakeStore()
    with patch("src.rag.flyer_pricing.get_vectorstore", return_value=store):
        records = lookup_flyer_pricing(query="HEK293 cost")

    # Focused search ran but its hit was deduped against the unfiltered
    # pool — only one primary record for that chunk.
    assert store.focused_calls == 1
    primaries = [r for r in records if r["_chunk_role"] == "primary"]
    assert len(primaries) == 1
    assert primaries[0]["source_section"] == "Plans"


def test_lookup_flyer_pricing_skips_focused_search_without_preferred_service():
    pricing = _make_chunk(
        {"service_name": "X",
         "section_type": "pricing_overview", "section_title": "Plans"}
    )

    class _FakeStore:
        def __init__(self):
            self.focused_calls = 0

        def similarity_search_with_score(self, query, k, filter=None):
            if filter is None:
                return [(pricing, 0.9)]
            self.focused_calls += 1
            return []

    store = _FakeStore()
    with patch("src.rag.flyer_pricing.get_vectorstore", return_value=store):
        lookup_flyer_pricing(query="how much for protein in general?")
    assert store.focused_calls == 0
