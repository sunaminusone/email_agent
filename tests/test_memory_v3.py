"""Tests for the v4-compatible memory lifecycle: recall, reflect, and drift handling."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.models import IntentGroup, ObjectRef
from src.memory.models import (
    BASE_WEIGHT_MAP,
    ClarificationMemory,
    ConversationTrajectory,
    IntentMemory,
    MemoryContribution,
    MemorySnapshot,
    ObjectMemory,
    ResponseMemory,
    ScoredObjectRef,
    ThreadMemory,
    compute_salience,
    salience_to_relevance,
)
from src.memory.recall import (
    _compute_overlap_signals,
    _compute_trajectory,
    _detect_intent_drift,
    _score_recent_objects,
    recall,
)
from src.memory.reflect import (
    _apply_salience_decay,
    _merge_contributions,
    _store_intent_groups,
    reflect,
)


# ---------------------------------------------------------------------------
# Salience scoring
# ---------------------------------------------------------------------------

class TestSalienceScoring:
    def test_compute_salience_basic(self):
        assert compute_salience(1.0, 1, 1) == 1.0
        assert compute_salience(2.5, 5, 1) == 12.5
        assert compute_salience(2.5, 5, 3) == 2.5 * 5 / 3

    def test_compute_salience_zero_turn_age_uses_one(self):
        assert compute_salience(1.0, 1, 0) == 1.0

    def test_salience_to_relevance_thresholds(self):
        assert salience_to_relevance(3.0) == "high"
        assert salience_to_relevance(2.0) == "high"
        assert salience_to_relevance(1.0) == "medium"
        assert salience_to_relevance(0.5) == "medium"
        assert salience_to_relevance(0.3) == "low"

    def test_biotech_keystone_survives_turn_gap(self):
        """CD19 (scientific_target) mentioned 5 times should remain high after 3 turns."""
        base_weight = BASE_WEIGHT_MAP["scientific_target"]  # 2.5
        sal = compute_salience(base_weight, 5, 3)
        assert salience_to_relevance(sal) == "high"

    def test_one_shot_invoice_decays_quickly(self):
        """Invoice mentioned once should be low after 4 turns."""
        base_weight = BASE_WEIGHT_MAP["invoice"]  # 1.0
        sal = compute_salience(base_weight, 1, 4)
        assert salience_to_relevance(sal) == "low"

    def test_score_recent_objects_sorts_by_salience(self):
        snapshot = MemorySnapshot(
            object_memory=ObjectMemory(
                active_object=ObjectRef(object_type="product", identifier="A100"),
                recent_objects=[
                    ObjectRef(object_type="invoice", identifier="INV-1", turn_age=4, interaction_count=1),
                    ObjectRef(object_type="scientific_target", identifier="CD19", turn_age=3, interaction_count=5),
                    ObjectRef(object_type="product", identifier="A100", turn_age=1, interaction_count=2),
                ],
            )
        )
        scored = _score_recent_objects(snapshot)
        assert len(scored) == 3
        assert scored[0].object_ref.identifier == "CD19"  # highest salience
        assert scored[0].relevance == "high"
        assert scored[2].object_ref.identifier == "INV-1"  # lowest salience
        assert scored[2].relevance == "low"
        # A100 should be marked active
        a100 = next(s for s in scored if s.object_ref.identifier == "A100")
        assert a100.is_active is True


# ---------------------------------------------------------------------------
# Trajectory detection
# ---------------------------------------------------------------------------

class TestTrajectoryDetection:
    def test_fresh_start(self):
        snapshot = MemorySnapshot()
        t = _compute_trajectory(snapshot)
        assert t.phase == "fresh_start"

    def test_clarification_loop(self):
        snapshot = MemorySnapshot(
            thread_memory=ThreadMemory(thread_id="t1", active_route="execute"),
            clarification_memory=ClarificationMemory(
                pending_clarification_type="product_selection",
            ),
        )
        t = _compute_trajectory(snapshot)
        assert t.phase == "clarification_loop"
        assert t.has_pending_clarification is True

    def test_follow_up(self):
        snapshot = MemorySnapshot(
            thread_memory=ThreadMemory(thread_id="t1", active_route="execute", last_turn_type="csr_draft"),
            response_memory=ResponseMemory(last_response_topics=["knowledge_lookup"]),
        )
        t = _compute_trajectory(snapshot)
        assert t.phase == "follow_up"

    def test_follow_up_legacy_turn_type_still_supported(self):
        snapshot = MemorySnapshot(
            thread_memory=ThreadMemory(thread_id="t1", active_route="execute", last_turn_type="answer"),
        )
        t = _compute_trajectory(snapshot)
        assert t.phase == "follow_up"

    def test_mid_topic(self):
        snapshot = MemorySnapshot(
            thread_memory=ThreadMemory(thread_id="t1", active_route="execute", last_turn_type=""),
            object_memory=ObjectMemory(
                active_object=ObjectRef(object_type="product", identifier="A100"),
            ),
        )
        t = _compute_trajectory(snapshot)
        assert t.phase == "mid_topic"

    def test_topic_switch_fallback(self):
        snapshot = MemorySnapshot(
            thread_memory=ThreadMemory(thread_id="t1", active_route="execute", last_turn_type=""),
        )
        t = _compute_trajectory(snapshot)
        assert t.phase == "topic_switch"


# ---------------------------------------------------------------------------
# Intent drift detection
# ---------------------------------------------------------------------------

class TestIntentDrift:
    def _make_groups(self, *intents_and_objects):
        """Helper: _make_groups(("technical_question", "CAR-T"), ("order_support", "12345"))"""
        groups = []
        for intent, display_name in intents_and_objects:
            groups.append(IntentGroup(
                intent=intent,
                object_display_name=display_name,
                confidence=0.85,
            ))
        return groups

    def test_no_prior_groups_returns_clear(self):
        drift = _detect_intent_drift(
            user_query="anything",
            prior_groups=[],
            trajectory=ConversationTrajectory(phase="follow_up"),
        )
        assert drift.drift_action == "clear"
        assert drift.continuity_confidence == 0.0

    def test_fresh_start_clears(self):
        groups = self._make_groups(("technical_question", "CAR-T"))
        drift = _detect_intent_drift(
            user_query="tell me more about CAR-T",
            prior_groups=groups,
            trajectory=ConversationTrajectory(phase="fresh_start"),
        )
        assert drift.drift_action == "clear"

    def test_clarification_loop_preserves(self):
        groups = self._make_groups(("technical_question", "CAR-T"))
        drift = _detect_intent_drift(
            user_query="the first one",
            prior_groups=groups,
            trajectory=ConversationTrajectory(phase="clarification_loop"),
        )
        assert drift.drift_action == "preserve"
        assert drift.continuity_confidence == 1.0
        assert len(drift.resolved_groups) == 1

    def test_follow_up_with_entity_match_preserves(self):
        groups = self._make_groups(("technical_question", "CAR-T"))
        drift = _detect_intent_drift(
            user_query="tell me more about CAR-T mechanism",
            prior_groups=groups,
            trajectory=ConversationTrajectory(phase="follow_up"),
        )
        assert drift.drift_action == "preserve"
        assert drift.continuity_confidence >= 0.7

    def test_follow_up_language_only_gives_moderate(self):
        groups = self._make_groups(("technical_question", "CAR-T"))
        drift = _detect_intent_drift(
            user_query="tell me more about that",
            prior_groups=groups,
            trajectory=ConversationTrajectory(phase="follow_up"),
        )
        # "tell me more" matches follow-up language (0.3) but no entity match
        assert drift.drift_action in {"merge", "preserve"}
        assert drift.continuity_confidence >= 0.3

    def test_new_entity_reduces_confidence(self):
        groups = self._make_groups(("technical_question", "CAR-T"))
        drift = _detect_intent_drift(
            user_query="what about product 20001",
            prior_groups=groups,
            trajectory=ConversationTrajectory(phase="follow_up"),
        )
        # New identifier "20001" detected, reduces score
        assert drift.continuity_confidence < 0.5

    def test_complete_topic_switch_clears(self):
        groups = self._make_groups(("technical_question", "CAR-T"))
        drift = _detect_intent_drift(
            user_query="check my invoice",
            prior_groups=groups,
            trajectory=ConversationTrajectory(phase="follow_up"),
        )
        assert drift.drift_action in {"clear", "stack"}
        assert drift.continuity_confidence < 0.3

    def test_chinese_follow_up_detected(self):
        groups = self._make_groups(("technical_question", "CAR-T"))
        drift = _detect_intent_drift(
            user_query="关于这个再说说",
            prior_groups=groups,
            trajectory=ConversationTrajectory(phase="follow_up"),
        )
        assert drift.continuity_confidence >= 0.3
        assert any("follow_up_language" in s for s in drift.reason.split(", ") if "follow_up" in s) or drift.drift_action in {"merge", "preserve"}


# ---------------------------------------------------------------------------
# Recall integration
# ---------------------------------------------------------------------------

class TestRecall:
    def test_recall_produces_memory_context(self):
        snapshot = MemorySnapshot(
            thread_memory=ThreadMemory(thread_id="t1", active_route="execute", last_turn_type="answer"),
            object_memory=ObjectMemory(
                active_object=ObjectRef(object_type="product", identifier="A100", display_name="CD3"),
                recent_objects=[
                    ObjectRef(object_type="product", identifier="A100", display_name="CD3", turn_age=0, interaction_count=3),
                ],
            ),
            response_memory=ResponseMemory(
                revealed_attributes=["identity", "applications"],
                last_response_topics=["knowledge_lookup"],
            ),
        )

        ctx = recall(thread_id="t1", user_query="tell me more about CD3", prior_state=snapshot)

        assert ctx.trajectory.phase == "follow_up"
        assert ctx.active_object is not None
        assert ctx.active_object.identifier == "A100"
        assert len(ctx.recent_objects_by_relevance) == 1
        assert ctx.recent_objects_by_relevance[0].relevance in {"high", "medium"}
        assert ctx.revealed_attributes == ["identity", "applications"]

    def test_recall_from_empty_state(self):
        ctx = recall(thread_id="t1", user_query="hello", prior_state=None)
        assert ctx.trajectory.phase == "fresh_start"
        assert ctx.active_object is None
        assert ctx.prior_intent_groups == []
        assert ctx.intent_continuity_confidence == 0.0

    def test_recall_surfaces_prior_intent_groups_when_following_up(self):
        groups = [IntentGroup(intent="technical_question", object_display_name="CAR-T", confidence=0.85)]
        snapshot = MemorySnapshot(
            thread_memory=ThreadMemory(thread_id="t1", active_route="execute", last_turn_type="csr_draft"),
            response_memory=ResponseMemory(last_response_topics=["knowledge_lookup"]),
            intent_memory=IntentMemory(
                prior_intent_groups=groups,
                prior_semantic_intent="technical_question",
            ),
        )
        ctx = recall(thread_id="t1", user_query="tell me more about CAR-T", prior_state=snapshot)
        assert len(ctx.prior_intent_groups) == 1
        assert ctx.prior_intent_groups[0].intent == "technical_question"
        assert ctx.intent_continuity_confidence >= 0.7


# ---------------------------------------------------------------------------
# Reflect: contribution merging
# ---------------------------------------------------------------------------

class TestReflectMergeContributions:
    def test_merge_basic_contributions(self):
        contribs = [
            MemoryContribution(
                source="objects",
                set_active_object=ObjectRef(object_type="product", identifier="A100"),
                append_recent_objects=[ObjectRef(object_type="product", identifier="A100")],
            ),
            MemoryContribution(
                source="routing",
                active_route="execute",
            ),
            MemoryContribution(
                source="response",
                mark_revealed_attributes=["identity", "price"],
                set_last_response_topics=["pricing_question"],
            ),
        ]
        update = _merge_contributions(contribs, "t1", "find product A100", "csr_draft")

        assert update.thread_memory.thread_id == "t1"
        assert update.thread_memory.active_route == "execute"
        assert update.set_active_object.identifier == "A100"
        assert update.mark_revealed_attributes == ["identity", "price"]
        assert update.set_last_response_topics == ["pricing_question"]

    def test_merge_soft_reset_wins(self):
        contribs = [
            MemoryContribution(source="routing", active_route="execute"),
            MemoryContribution(source="response", soft_reset_current_topic=True),
        ]
        update = _merge_contributions(contribs, "t1", "", "")
        assert update.soft_reset_current_topic is True

    def test_merge_last_writer_wins_for_scalars(self):
        contribs = [
            MemoryContribution(source="routing", active_route="clarify"),
            MemoryContribution(source="response", active_route="execute"),
        ]
        update = _merge_contributions(contribs, "t1", "", "")
        assert update.thread_memory.active_route == "execute"

    def test_merge_lists_concatenate(self):
        contribs = [
            MemoryContribution(source="objects", append_recent_objects=[
                ObjectRef(object_type="product", identifier="A100"),
            ]),
            MemoryContribution(source="objects", append_recent_objects=[
                ObjectRef(object_type="order", identifier="12345"),
            ]),
        ]
        update = _merge_contributions(contribs, "t1", "", "")
        assert len(update.append_recent_objects) == 2


# ---------------------------------------------------------------------------
# Reflect: salience decay
# ---------------------------------------------------------------------------

class TestSalienceDecay:
    def test_referenced_object_gets_count_bumped_and_age_reset(self):
        snapshot = MemorySnapshot(
            object_memory=ObjectMemory(
                active_object=ObjectRef(object_type="product", identifier="A100"),
                recent_objects=[
                    ObjectRef(object_type="product", identifier="A100", turn_age=3, interaction_count=2),
                    ObjectRef(object_type="order", identifier="12345", turn_age=3, interaction_count=1),
                ],
            ),
        )
        result = _apply_salience_decay(snapshot)
        refs = result.object_memory.recent_objects

        a100 = next(r for r in refs if r.identifier == "A100")
        assert a100.turn_age == 1  # reset
        assert a100.interaction_count == 3  # bumped

        order = next(r for r in refs if r.identifier == "12345")
        assert order.turn_age == 4  # incremented from 3
        assert order.interaction_count == 1  # unchanged

    def test_low_salience_object_evicted(self):
        snapshot = MemorySnapshot(
            object_memory=ObjectMemory(
                recent_objects=[
                    ObjectRef(object_type="invoice", identifier="INV-1", turn_age=10, interaction_count=1),
                ],
            ),
        )
        result = _apply_salience_decay(snapshot)
        # salience = 1.0 * 1 / 11 = 0.09 < 0.3 threshold
        assert len(result.object_memory.recent_objects) == 0

    def test_high_interaction_object_survives(self):
        snapshot = MemorySnapshot(
            object_memory=ObjectMemory(
                recent_objects=[
                    ObjectRef(object_type="scientific_target", identifier="CD19", turn_age=8, interaction_count=5),
                ],
            ),
        )
        result = _apply_salience_decay(snapshot)
        # salience = 2.5 * 5 / 9 = 1.39 ≥ 0.3
        assert len(result.object_memory.recent_objects) == 1
        assert result.object_memory.recent_objects[0].turn_age == 9


# ---------------------------------------------------------------------------
# Reflect: intent group storage
# ---------------------------------------------------------------------------

class TestIntentGroupStorage:
    def test_soft_reset_clears_all(self):
        snapshot = MemorySnapshot(
            intent_memory=IntentMemory(
                prior_intent_groups=[IntentGroup(intent="technical_question")],
                stacked_intent_history=[[IntentGroup(intent="order_support")]],
            ),
        )
        contribs = [MemoryContribution(source="response", soft_reset_current_topic=True)]
        result = _store_intent_groups(snapshot, contribs)
        assert result.intent_memory.prior_intent_groups == []
        assert result.intent_memory.stacked_intent_history == []

    def test_new_groups_replace_prior(self):
        snapshot = MemorySnapshot(
            intent_memory=IntentMemory(
                prior_intent_groups=[IntentGroup(intent="order_support")],
            ),
        )
        new_groups = [IntentGroup(intent="technical_question", object_display_name="CAR-T")]
        contribs = [MemoryContribution(source="ingestion", intent_groups=new_groups)]
        result = _store_intent_groups(snapshot, contribs)
        assert len(result.intent_memory.prior_intent_groups) == 1
        assert result.intent_memory.prior_intent_groups[0].intent == "technical_question"
        # Old groups pushed to stack
        assert len(result.intent_memory.stacked_intent_history) == 1

    def test_same_intents_dont_stack(self):
        snapshot = MemorySnapshot(
            intent_memory=IntentMemory(
                prior_intent_groups=[IntentGroup(intent="technical_question")],
            ),
        )
        new_groups = [IntentGroup(intent="technical_question", object_display_name="CAR-T")]
        contribs = [MemoryContribution(source="ingestion", intent_groups=new_groups)]
        result = _store_intent_groups(snapshot, contribs)
        assert len(result.intent_memory.stacked_intent_history) == 0  # no stack since same intent

    def test_no_new_groups_increments_counter(self):
        snapshot = MemorySnapshot(
            intent_memory=IntentMemory(
                prior_intent_groups=[IntentGroup(intent="technical_question")],
                turns_since_last_intent_change=2,
            ),
        )
        contribs = [MemoryContribution(source="routing", active_route="execute")]
        result = _store_intent_groups(snapshot, contribs)
        assert result.intent_memory.turns_since_last_intent_change == 3

    def test_follow_up_intent_does_not_overwrite_prior_semantic_intent(self):
        """Chain follow-ups must keep prior_semantic_intent pointing at the
        last meaningful retrieval bucket (backlog #8 writer side)."""
        snapshot = MemorySnapshot(
            intent_memory=IntentMemory(
                prior_intent_groups=[IntentGroup(intent="pricing_question")],
                prior_semantic_intent="pricing_question",
            ),
        )
        new_groups = [IntentGroup(intent="follow_up", object_display_name="CAR-T")]
        contribs = [MemoryContribution(source="ingestion", intent_groups=new_groups)]
        result = _store_intent_groups(snapshot, contribs)
        # prior_intent_groups gets the new follow_up group (drift tracking unchanged)
        assert result.intent_memory.prior_intent_groups[0].intent == "follow_up"
        # But prior_semantic_intent stays pinned to the meaningful intent
        assert result.intent_memory.prior_semantic_intent == "pricing_question"

    def test_unknown_intent_does_not_overwrite_prior_semantic_intent(self):
        snapshot = MemorySnapshot(
            intent_memory=IntentMemory(
                prior_intent_groups=[IntentGroup(intent="technical_question")],
                prior_semantic_intent="technical_question",
            ),
        )
        new_groups = [IntentGroup(intent="unknown")]
        contribs = [MemoryContribution(source="ingestion", intent_groups=new_groups)]
        result = _store_intent_groups(snapshot, contribs)
        assert result.intent_memory.prior_semantic_intent == "technical_question"

    def test_stack_depth_limited(self):
        snapshot = MemorySnapshot(
            intent_memory=IntentMemory(
                prior_intent_groups=[IntentGroup(intent="group_4")],
                stacked_intent_history=[
                    [IntentGroup(intent="group_1")],
                    [IntentGroup(intent="group_2")],
                    [IntentGroup(intent="group_3")],
                ],
            ),
        )
        new_groups = [IntentGroup(intent="group_5")]
        contribs = [MemoryContribution(source="ingestion", intent_groups=new_groups)]
        result = _store_intent_groups(snapshot, contribs)
        # Stack should be capped at 3
        assert len(result.intent_memory.stacked_intent_history) == 3
        # Oldest (group_1) should be evicted
        stack_intents = [g[0].intent for g in result.intent_memory.stacked_intent_history]
        assert "group_1" not in stack_intents


# ---------------------------------------------------------------------------
# Reflect integration
# ---------------------------------------------------------------------------

class TestReflectIntegration:
    def test_reflect_full_cycle(self):
        snapshot = MemorySnapshot(
            thread_memory=ThreadMemory(thread_id="t1"),
            object_memory=ObjectMemory(
                recent_objects=[
                    ObjectRef(object_type="product", identifier="A100", turn_age=0, interaction_count=1),
                ],
            ),
        )

        contribs = [
            MemoryContribution(
                source="objects",
                set_active_object=ObjectRef(object_type="product", identifier="A100"),
                append_recent_objects=[ObjectRef(object_type="product", identifier="A100")],
            ),
            MemoryContribution(
                source="routing",
                active_route="execute",
            ),
            MemoryContribution(
                source="ingestion",
                intent_groups=[IntentGroup(intent="product_inquiry", object_identifier="A100")],
            ),
            MemoryContribution(
                source="response",
                mark_revealed_attributes=["identity"],
                set_last_response_topics=["product_inquiry"],
            ),
        ]

        result = reflect(
            current_snapshot=snapshot,
            contributions=contribs,
            thread_id="t1",
            normalized_query="find product A100",
            last_turn_type="csr_draft",
        )

        assert result.thread_memory.active_route == "execute"
        assert result.thread_memory.last_user_goal == "find product A100"
        assert result.response_memory.revealed_attributes == ["identity"]
        assert result.intent_memory.prior_intent_groups[0].intent == "product_inquiry"
        # A100 should have interaction_count bumped (was in both recent + active)
        a100_refs = [r for r in result.object_memory.recent_objects if r.identifier == "A100"]
        assert len(a100_refs) >= 1
        assert a100_refs[0].interaction_count >= 2

    def test_multi_intent_then_follow_up(self):
        """Simulate turn 1 (multi-intent) then turn 2 (follow-up)."""
        # Turn 1: create multi-intent snapshot
        snapshot_t1 = MemorySnapshot(thread_memory=ThreadMemory(thread_id="t1"))
        contribs_t1 = [
            MemoryContribution(
                source="objects",
                set_active_object=ObjectRef(object_type="order", identifier="12345"),
                append_recent_objects=[
                    ObjectRef(object_type="order", identifier="12345"),
                    ObjectRef(object_type="product", display_name="CAR-T"),
                ],
            ),
            MemoryContribution(
                source="ingestion",
                intent_groups=[
                    IntentGroup(intent="order_support", object_identifier="12345"),
                    IntentGroup(intent="technical_question", object_display_name="CAR-T"),
                ],
            ),
            MemoryContribution(source="routing", active_route="execute"),
            MemoryContribution(source="response", set_last_response_topics=["order_support", "technical_question"]),
        ]
        snapshot_t2_start = reflect(
            current_snapshot=snapshot_t1,
            contributions=contribs_t1,
            thread_id="t1",
            normalized_query="check order 12345 and explain CAR-T",
            last_turn_type="csr_draft",
        )

        # Verify turn 1 results
        assert len(snapshot_t2_start.intent_memory.prior_intent_groups) == 2

        # Turn 2: recall with follow-up query
        ctx = recall(
            thread_id="t1",
            user_query="tell me more about CAR-T",
            prior_state=snapshot_t2_start,
        )
        assert ctx.intent_continuity_confidence > 0
        assert any(g.intent == "technical_question" for g in ctx.prior_intent_groups) or ctx.trajectory.phase == "follow_up"
