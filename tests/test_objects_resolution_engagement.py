from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.models import ObjectRef
from src.ingestion.models import (
    AttributeConstraint,
    IngestionBundle,
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
    _candidate_score,
    _classify_engagement,
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


def _candidate(source_type: str, confidence: float = 0.5) -> ObjectCandidate:
    return ObjectCandidate(
        object_type="product",
        display_name="X",
        canonical_value="X",
        confidence=confidence,
        recency="CONTEXTUAL",
        source_type=source_type,
    )


def _classify(
    bundle: IngestionBundle,
    *,
    current=None,
    context=None,
    ambiguous=None,
    trajectory_phase: str | None = None,
) -> _ContextEngagement:
    return _classify_engagement(
        bundle,
        current_candidates=current or [],
        context_candidates=context or [],
        ambiguous_sets=ambiguous or [],
        trajectory_phase=trajectory_phase,
    )


# ---------------------------------------------------------------------------
# context_reuse decision
# ---------------------------------------------------------------------------

def test_no_signals_decides_inert():
    e = _classify(IngestionBundle())
    assert e.can_reuse_context is False
    assert e.has_pending_clarification is False
    assert e.constraint_target_mode == "none"


def test_reference_intent_unlocks_context_reuse():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(is_context_dependent=True),
        ),
    )
    e = _classify(bundle)
    assert e.can_reuse_context is True


def test_topic_switch_blocks_context_reuse():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(is_context_dependent=True),
        ),
    )
    e = _classify(bundle, trajectory_phase="topic_switch")
    assert e.can_reuse_context is False


def test_fresh_start_blocks_context_reuse():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(is_context_dependent=True),
        ),
    )
    e = _classify(bundle, trajectory_phase="fresh_start")
    assert e.can_reuse_context is False


# ---------------------------------------------------------------------------
# constraint_target_mode decision
# ---------------------------------------------------------------------------

def test_constraints_alone_do_not_apply():
    """Constraints without reference intent or pending clarification → mode=none."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                attribute_constraints=[_constraint("species", "human")],
            ),
        ),
    )
    e = _classify(bundle)
    assert e.constraint_target_mode == "none"


def test_pending_clarification_with_ambiguous_sets_targets_pending_only():
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
    fake_set = object()  # classifier doesn't inspect shape, only truthiness
    e = _classify(bundle, ambiguous=[fake_set])
    assert e.has_pending_clarification is True
    assert e.constraint_target_mode == "pending_only"


def test_reference_intent_with_context_targets_context_only():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                is_context_dependent=True,
                attribute_constraints=[_constraint("species", "human")],
            ),
        ),
    )
    fake_ctx = object()
    e = _classify(bundle, context=[fake_ctx])
    assert e.constraint_target_mode == "context_only"


def test_reference_intent_no_context_no_ambiguous_targets_current_only():
    """Constraints + reference intent + only current weak candidates → current_only."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                is_context_dependent=True,
                attribute_constraints=[_constraint("species", "human")],
            ),
        ),
    )
    weak_current = _candidate("parser", confidence=0.3)
    e = _classify(bundle, current=[weak_current])
    assert e.constraint_target_mode == "current_only"


# ---------------------------------------------------------------------------
# _candidate_score: pending_option must not compete for primary
# ---------------------------------------------------------------------------

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

    if resolved.primary_object is not None:
        assert resolved.primary_object.source_type != "pending_option"
