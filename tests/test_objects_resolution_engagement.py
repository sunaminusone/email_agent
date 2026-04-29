from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.models import ObjectRef
from src.ingestion.models import (
    AttributeConstraint,
    EntitySpan,
    IngestionBundle,
    ParserEntitySignals,
    ParserSignals,
    ReferenceSignals,
    SourceAttribution,
    TurnSignals,
)
from src.memory.models import (
    ClarificationMemory,
    MemoryContext,
    MemorySnapshot,
    ScoredObjectRef,
)
from src.objects.models import ObjectCandidate
from src.objects.resolution import (
    _build_engagement,
    _candidate_score,
    _constraint_target_mode,
    _ContextEngagement,
    resolve_objects,
)


def _constraint(attribute: str, value: str) -> AttributeConstraint:
    return AttributeConstraint(
        attribute=attribute,
        value=value,
        attribution=SourceAttribution(source_type="parser", recency="CURRENT_TURN"),
    )


def _scored_ref(display_name: str, identifier: str, salience: float = 0.8) -> ScoredObjectRef:
    return ScoredObjectRef(
        object_ref=ObjectRef(
            object_type="product",
            identifier=identifier,
            display_name=display_name,
        ),
        salience=salience,
    )


# ---------------------------------------------------------------------------
# _ContextEngagement aggregation
# ---------------------------------------------------------------------------

def test_engagement_no_signals():
    bundle = IngestionBundle()
    e = _build_engagement(bundle, trajectory_phase=None)
    assert not e.has_reference_intent
    assert not e.has_pending_clarification
    assert not e.has_constraints
    assert not e.blocks_context_reuse
    assert not e.can_reuse_context
    assert not e.should_apply_constraints


def test_engagement_reference_intent_from_context_dependence():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(is_context_dependent=True),
        ),
    )
    e = _build_engagement(bundle, trajectory_phase=None)
    assert e.has_reference_intent
    assert e.can_reuse_context


def test_engagement_blocks_reuse_on_topic_switch():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(is_context_dependent=True),
        ),
    )
    e = _build_engagement(bundle, trajectory_phase="topic_switch")
    assert e.has_reference_intent
    assert e.blocks_context_reuse
    assert not e.can_reuse_context


def test_engagement_blocks_reuse_on_fresh_start():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(is_context_dependent=True),
        ),
    )
    e = _build_engagement(bundle, trajectory_phase="fresh_start")
    assert e.blocks_context_reuse
    assert not e.can_reuse_context


def test_engagement_should_apply_constraints_requires_constraints_and_intent():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                is_context_dependent=True,
                attribute_constraints=[_constraint("species", "human")],
            ),
        ),
    )
    e = _build_engagement(bundle, trajectory_phase=None)
    assert e.should_apply_constraints


def test_engagement_constraints_alone_do_not_trigger_apply():
    """Constraints without reference intent or pending clarification → don't apply."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                attribute_constraints=[_constraint("species", "human")],
            ),
        ),
    )
    e = _build_engagement(bundle, trajectory_phase=None)
    assert e.has_constraints
    assert not e.has_reference_intent
    assert not e.has_pending_clarification
    assert not e.should_apply_constraints


def test_engagement_pending_clarification_unlocks_constraint_apply():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                attribute_constraints=[_constraint("species", "human")],
            ),
        ),
        memory_context=MemoryContext(
            snapshot=MemorySnapshot(
                clarification_memory=ClarificationMemory(
                    pending_clarification_type="product_selection",
                ),
            ),
        ),
    )
    e = _build_engagement(bundle, trajectory_phase=None)
    assert e.has_pending_clarification
    assert e.should_apply_constraints


# ---------------------------------------------------------------------------
# _constraint_target_mode (engagement-driven)
# ---------------------------------------------------------------------------

def test_constraint_target_mode_none_when_no_apply():
    e = _ContextEngagement(False, False, False, False)
    assert _constraint_target_mode(e, [], [], []) == "none"


def test_constraint_target_mode_pending_only_when_clarification_and_ambiguous():
    e = _ContextEngagement(
        has_reference_intent=False,
        has_pending_clarification=True,
        has_constraints=True,
        blocks_context_reuse=False,
    )
    fake_set = object()
    assert _constraint_target_mode(e, [], [], [fake_set]) == "pending_only"


def test_constraint_target_mode_context_only_with_context_and_intent():
    e = _ContextEngagement(
        has_reference_intent=True,
        has_pending_clarification=False,
        has_constraints=True,
        blocks_context_reuse=False,
    )
    fake_ctx = object()
    assert _constraint_target_mode(e, [], [fake_ctx], []) == "context_only"


# ---------------------------------------------------------------------------
# _candidate_score: pending_option must not compete for primary
# ---------------------------------------------------------------------------

def _candidate(source_type: str, confidence: float = 0.5) -> ObjectCandidate:
    return ObjectCandidate(
        object_type="product",
        display_name="X",
        canonical_value="X",
        confidence=confidence,
        recency="CONTEXTUAL",
        source_type=source_type,
    )


def test_score_recent_object_lightly_penalized():
    score = _candidate_score(_candidate("recent_object", confidence=0.5))
    # 0.5 confidence - 0.05 source = 0.45
    assert abs(score - 0.45) < 1e-9


def test_score_pending_option_heavily_penalized():
    """Pending options must score below any plausible recent_object so they
    cannot win the primary_object competition without selection_resolution."""
    pending_score = _candidate_score(_candidate("pending_option", confidence=0.95))
    recent_score = _candidate_score(_candidate("recent_object", confidence=0.05))
    assert pending_score < recent_score


def test_pending_option_does_not_bubble_up_as_primary_via_context_reuse():
    """Even with high local confidence, pending_option candidates must not
    win primary slot purely through context_reuse path."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                is_context_dependent=True,
                reference_mode="active",
            ),
        ),
        memory_context=MemoryContext(
            snapshot=MemorySnapshot(
                clarification_memory=ClarificationMemory(
                    pending_clarification_type="product_selection",
                    pending_candidate_options=["Anti-CD4 OKT4", "Anti-CD4 SK3"],
                    pending_identifier="candidate set",
                ),
            ),
        ),
    )
    recent = [_scored_ref("Some Recent Product", "P00099", salience=0.9)]
    resolved = resolve_objects(bundle, recent_objects=recent)

    # primary should come from recent_object (not from a pending_option)
    if resolved.primary_object is not None:
        assert resolved.primary_object.source_type != "pending_option"
