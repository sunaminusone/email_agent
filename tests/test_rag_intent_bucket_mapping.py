from __future__ import annotations

import warnings

import pytest

from src.ingestion.models import SEMANTIC_INTENT_VALUES
from src.rag import detect_intent_bucket, get_bucket_mode

# Underscored tables are test-visible internals: invariant tests need to reach
# into them to assert completeness (every intent has a bucket, every bucket has
# a mode, ranked ↔ section boosts). Public callers should use the helpers above.
from src.rag.query_scope import _BUCKET_MODES, _SEMANTIC_INTENT_BUCKET_MAP
from src.rag.retriever import _SECTION_TYPE_BOOSTS


def test_every_canonical_semantic_intent_has_explicit_bucket() -> None:
    missing = [intent for intent in SEMANTIC_INTENT_VALUES if intent not in _SEMANTIC_INTENT_BUCKET_MAP]
    assert missing == [], (
        f"Every canonical semantic_intent must have an explicit bucket in "
        f"_SEMANTIC_INTENT_BUCKET_MAP. Missing: {missing}"
    )


@pytest.mark.parametrize(
    "semantic_intent,expected_bucket",
    [
        ("pricing_question", "pricing"),
        ("timeline_question", "timeline"),
        ("workflow_question", "workflow"),
        ("model_support_question", "model_support"),
        ("service_plan_question", "service_plan"),
        ("documentation_request", "documentation"),
        ("customization_request", "customization"),
        ("technical_question", "general_technical"),
        ("troubleshooting", "general_technical"),
        ("product_inquiry", "general_technical"),
        ("shipping_question", "operational"),
        ("order_support", "operational"),
        ("complaint", "operational"),
        ("general_info", "general_info"),
        ("follow_up", "follow_up"),
        ("unknown", "unknown"),
    ],
)
def test_canonical_intent_projects_one_to_one(semantic_intent: str, expected_bucket: str) -> None:
    # Query text should be ignored when semantic_intent is present — parser is
    # authoritative.
    assert detect_intent_bucket("any query text", semantic_intent) == expected_bucket


def test_empty_intent_falls_back_to_keyword_detection() -> None:
    # Parser absent: keyword fallback kicks in (legacy callers / rows without
    # semantic_intent).
    assert detect_intent_bucket("what is the service plan and timeline", "") == "service_plan"
    assert detect_intent_bucket("walk me through the workflow", "") == "workflow"
    assert detect_intent_bucket("which models do you support", "") == "model_support"
    assert detect_intent_bucket("tell me about the project", "") == "general_technical"
    assert detect_intent_bucket("", "") == "general_technical"


def test_non_canonical_intent_warns_and_defaults_to_general_technical() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bucket = detect_intent_bucket("anything", "fictional_new_intent")
    assert bucket == "general_technical"
    assert any("unmapped semantic_intent" in str(w.message) for w in caught)


def test_unknown_intent_uses_explicit_bucket_not_keyword_fallback() -> None:
    # Parser explicitly said "unknown" — respect that, don't re-guess via keywords.
    assert detect_intent_bucket("service plan timeline phase", "unknown") == "unknown"


_VALID_BUCKET_MODES = {"ranked", "lexical_only", "non_rag", "placeholder"}


def test_every_bucket_in_map_has_mode() -> None:
    bucket_values = set(_SEMANTIC_INTENT_BUCKET_MAP.values())
    missing = [bucket for bucket in bucket_values if bucket not in _BUCKET_MODES]
    assert missing == [], f"Buckets without mode assignment: {missing}"


def test_all_modes_are_valid() -> None:
    invalid = {bucket: mode for bucket, mode in _BUCKET_MODES.items() if mode not in _VALID_BUCKET_MODES}
    assert invalid == {}, (
        f"Invalid bucket modes: {invalid}. Valid modes: {sorted(_VALID_BUCKET_MODES)}"
    )


def test_ranked_buckets_have_section_boosts() -> None:
    # Invariant: ranked ↔ presence in _SECTION_TYPE_BOOSTS. A ranked bucket
    # without boosts is either mis-classified or has a pending KB target.
    ranked = {bucket for bucket, mode in _BUCKET_MODES.items() if mode == "ranked"}
    missing_boosts = [bucket for bucket in ranked if not _SECTION_TYPE_BOOSTS.get(bucket)]
    assert missing_boosts == [], (
        f"ranked buckets without section boosts: {missing_boosts}. Either add "
        f"entries to _SECTION_TYPE_BOOSTS or reclassify as lexical_only."
    )


def test_non_ranked_buckets_have_no_section_boosts() -> None:
    # Invariant: lexical_only / non_rag / placeholder MUST NOT have section
    # boosts — if they did, they'd functionally be ranked.
    non_ranked = {bucket for bucket, mode in _BUCKET_MODES.items() if mode != "ranked"}
    leaked = [bucket for bucket in non_ranked if _SECTION_TYPE_BOOSTS.get(bucket)]
    assert leaked == [], (
        f"non-ranked buckets leaked into _SECTION_TYPE_BOOSTS: {leaked}. "
        f"Either reclassify as ranked or remove the boost entry."
    )


def test_get_bucket_mode_returns_empty_for_unknown_bucket() -> None:
    assert get_bucket_mode("not_a_real_bucket") == ""
    assert get_bucket_mode("") == ""


@pytest.mark.parametrize(
    "bucket,expected_mode",
    [
        ("pricing", "ranked"),
        ("timeline", "ranked"),
        ("workflow", "ranked"),
        ("model_support", "ranked"),
        ("service_plan", "ranked"),
        ("general_technical", "lexical_only"),
        ("documentation", "lexical_only"),
        ("customization", "lexical_only"),
        ("operational", "non_rag"),
        ("general_info", "lexical_only"),
        ("follow_up", "placeholder"),
        ("unknown", "placeholder"),
    ],
)
def test_get_bucket_mode_returns_declared_mode(bucket: str, expected_mode: str) -> None:
    assert get_bucket_mode(bucket) == expected_mode
