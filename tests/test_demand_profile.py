from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.models import IntentGroup
from src.ingestion import build_demand_profile, narrow_demand_profile, is_truly_mixed
from src.ingestion.models import ParserContext, ParserRequestFlags, ParserSignals


def test_build_demand_profile_prefers_intent_aligned_primary_demand() -> None:
    parser_signals = ParserSignals(
        context=ParserContext(semantic_intent="technical_question"),
        request_flags=ParserRequestFlags(needs_protocol=True, needs_price=True),
    )
    intent_groups = [
        IntentGroup(
            intent="technical_question",
            request_flags=["needs_protocol"],
            object_type="product",
            object_identifier="P-100",
            object_display_name="CAR-T",
        ),
        IntentGroup(
            intent="pricing_question",
            request_flags=["needs_price"],
            object_type="product",
            object_identifier="P-100",
            object_display_name="CAR-T",
        ),
    ]

    profile = build_demand_profile(parser_signals, intent_groups)

    assert profile.primary_demand == "technical"
    assert profile.secondary_demands == ["commercial"]
    assert profile.active_request_flags == ["needs_price", "needs_protocol"] or profile.active_request_flags == ["needs_protocol", "needs_price"]
    assert len(profile.group_demands) == 2


def test_build_demand_profile_preserves_group_level_semantics() -> None:
    parser_signals = ParserSignals(
        context=ParserContext(semantic_intent="order_support"),
        request_flags=ParserRequestFlags(needs_order_status=True),
    )
    intent_groups = [
        IntentGroup(
            intent="order_support",
            request_flags=["needs_order_status"],
            object_type="order",
            object_identifier="SO-12345",
            object_display_name="Order SO-12345",
        ),
    ]

    profile = build_demand_profile(parser_signals, intent_groups)

    assert profile.primary_demand == "operational"
    assert profile.group_demands[0].primary_demand == "operational"
    assert profile.group_demands[0].object_identifier == "SO-12345"


def test_narrow_demand_profile_matches_focus_group() -> None:
    focus_group = IntentGroup(
        intent="documentation_request",
        request_flags=["needs_documentation"],
        object_type="service",
        object_identifier="",
        object_display_name="CAR-T service",
    )
    profile = build_demand_profile(
        ParserSignals(
            context=ParserContext(semantic_intent="documentation_request"),
            request_flags=ParserRequestFlags(needs_documentation=True),
        ),
        [focus_group],
    )

    scoped = narrow_demand_profile(profile, focus_group)

    assert scoped is not None
    assert scoped.primary_demand == "technical"
    assert scoped.request_flags == ["needs_documentation"]


# --- is_truly_mixed ---

def test_is_truly_mixed_different_families() -> None:
    assert is_truly_mixed("technical", ["commercial"]) is True

def test_is_truly_mixed_same_family() -> None:
    assert is_truly_mixed("technical", []) is False

def test_is_truly_mixed_secondary_only_general() -> None:
    """general is not a real demand family — should not trigger mixed."""
    assert is_truly_mixed("technical", ["general"]) is False

def test_is_truly_mixed_all_general() -> None:
    assert is_truly_mixed("general", ["general"]) is False

def test_is_truly_mixed_three_way() -> None:
    assert is_truly_mixed("technical", ["commercial", "operational"]) is True


# --- demand continuity ---

def test_continuity_boosts_weak_demand_confidence() -> None:
    """Follow-up in same demand lane: 0.4 (weak) boosted by prior context."""
    from src.ingestion.demand_profile import build_group_demand

    group = IntentGroup(intent="unknown", confidence=0.5)

    without = build_group_demand(group)
    assert without.demand_confidence == 0.4

    with_cont = build_group_demand(
        group,
        prior_demand_type="general",  # no real prior → no boost
        continuity_confidence=0.8,
    )
    assert with_cont.demand_confidence == 0.4  # still 0.4

    # Prior was technical, this group resolves to general, continuity high:
    # demand inherited from prior → technical with confidence 0.6
    inherited = build_group_demand(
        group,
        prior_demand_type="technical",
        prior_demand_flags=["needs_protocol"],
        continuity_confidence=0.8,
    )
    assert inherited.primary_demand == "technical"  # inherited
    assert inherited.demand_confidence == 0.6  # inherited, not directly observed
    assert inherited.request_flags == ["needs_protocol"]


def test_continuity_boosts_matching_intent_demand() -> None:
    """Follow-up with matching intent → confidence boosted from 0.7 to ~0.86."""
    from src.ingestion.demand_profile import build_group_demand

    group = IntentGroup(intent="technical_question", confidence=0.5)

    base = build_group_demand(group)
    assert base.demand_confidence == 0.7  # intent-derived, no flags

    boosted = build_group_demand(
        group,
        prior_demand_type="technical",
        continuity_confidence=0.8,
    )
    # 0.7 + min(0.8 * 0.2, 0.2) = 0.7 + 0.16 = 0.86
    assert boosted.demand_confidence > 0.7
    assert boosted.demand_confidence <= 0.9


def test_continuity_no_boost_when_already_strong() -> None:
    """Flags-derived 0.9 should NOT be boosted further."""
    from src.ingestion.demand_profile import build_group_demand

    group = IntentGroup(
        intent="technical_question",
        request_flags=["needs_protocol"],
        confidence=0.85,
    )

    boosted = build_group_demand(
        group,
        prior_demand_type="technical",
        continuity_confidence=1.0,
    )
    assert boosted.demand_confidence == 0.9  # capped, not 1.1


def test_no_inheritance_when_continuity_low() -> None:
    """Low continuity (< 0.5) should NOT inherit prior demand."""
    from src.ingestion.demand_profile import build_group_demand

    group = IntentGroup(intent="unknown", confidence=0.5)

    result = build_group_demand(
        group,
        prior_demand_type="technical",
        prior_demand_flags=["needs_protocol"],
        continuity_confidence=0.3,  # below threshold
    )
    assert result.primary_demand == "general"  # no inheritance
    assert result.demand_confidence == 0.4


def test_no_inheritance_without_prior_flags() -> None:
    from src.ingestion.demand_profile import build_group_demand

    group = IntentGroup(intent="follow_up", confidence=0.5)

    result = build_group_demand(
        group,
        prior_demand_type="technical",
        prior_demand_flags=[],
        continuity_confidence=0.9,
    )

    assert result.primary_demand == "general"
    assert result.request_flags == []
