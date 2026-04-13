from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.models import (
    AttributeConstraint,
    EntitySpan,
    IngestionBundle,
    ParserEntitySignals,
    ParserSignals,
    ReferenceSignals,
    SourceAttribution,
    StatefulAnchors,
    TurnSignals,
)
from src.common.models import ObjectRef
from src.memory.models import ScoredObjectRef
from src.objects.constraint_matching import candidate_matches_constraint
from src.objects.extraction import extract_object_bundle
from src.objects.models import ObjectCandidate
from src.objects.resolution import resolve_object_state, resolve_objects


def _constraint(attribute: str, value: str) -> AttributeConstraint:
    return AttributeConstraint(
        attribute=attribute,
        value=value,
        attribution=SourceAttribution(source_type="deterministic", recency="CURRENT_TURN"),
    )


def _scored_ref(display_name: str, identifier: str, salience: float, object_type: str = "product") -> ScoredObjectRef:
    return ScoredObjectRef(
        object_ref=ObjectRef(
            object_type=object_type,
            identifier=identifier,
            display_name=display_name,
        ),
        salience=salience,
    )


def test_nonreferential_constraints_do_not_filter_current_explicit_object():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                entities=ParserEntitySignals(
                    service_names=[EntitySpan(text="Flow Cytometry")],
                )
            ),
            reference_signals=ReferenceSignals(
                attribute_constraints=[_constraint("species", "human")],
            ),
        )
    )

    resolved = resolve_object_state(bundle, extract_object_bundle(bundle))

    assert resolved.primary_object is not None
    assert resolved.primary_object.display_name == "Flow Cytometry Services"
    assert (
        resolved.resolution_reason
        == "Selected the strongest current-turn object candidate."
    )


def test_referential_constraints_target_context_candidates_only():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                is_context_dependent=True,
                reference_mode="active",
                attribute_constraints=[_constraint("species", "human")],
            ),
        ),
    )
    recent = [
        _scored_ref("Rabbit Polyclonal antibody to ACTB", "P00001", salience=0.8),
    ]

    resolved = resolve_objects(bundle, recent_objects=recent)

    assert resolved.primary_object is None
    assert (
        resolved.resolution_reason
        == "Reference attribute constraints did not match the targeted contextual candidates."
    )


def test_service_phrase_fragment_resolves_to_canonical_service():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                entities=ParserEntitySignals(
                    service_names=[EntitySpan(text="Gamma Delta T Cell")],
                )
            ),
        )
    )

    resolved = resolve_object_state(bundle, extract_object_bundle(bundle))

    assert resolved.primary_object is not None
    assert resolved.primary_object.display_name == "Custom Gamma Delta T Cell Development"
    assert resolved.primary_object.metadata.get("matched_alias_kinds") == ["phrase_fragment"]


def test_service_abbreviation_variant_resolves_to_canonical_service():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                entities=ParserEntitySignals(
                    service_names=[EntitySpan(text="mRNA LNP Gene Delivery")],
                )
            ),
        )
    )

    resolved = resolve_object_state(bundle, extract_object_bundle(bundle))

    assert resolved.primary_object is not None
    assert resolved.primary_object.display_name == "mRNA-LNP Gene Delivery"
    assert "abbreviation" in resolved.primary_object.metadata.get("matched_alias_kinds", [])


def test_pending_only_constraints_promote_single_remaining_candidate_to_primary():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                attribute_constraints=[_constraint("species", "human")],
            ),
        ),
        stateful_anchors=StatefulAnchors(
            pending_clarification_field="product_selection",
            pending_candidate_options=[
                "Rabbit Monoclonal Antibody",
                "Human Monoclonal Antibody",
            ],
            pending_identifier="candidate set",
        ),
    )

    resolved = resolve_object_state(bundle, extract_object_bundle(bundle))

    assert resolved.primary_object is not None
    assert resolved.primary_object.display_name == "Human Monoclonal Antibody"
    assert resolved.ambiguous_sets == []
    assert resolved.secondary_objects == []
    assert (
        resolved.resolution_reason
        == "Resolved the pending clarification to a single object candidate."
    )


def test_product_ambiguity_kind_and_clarification_strategy_are_derived_from_alias_kind():
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                entities=ParserEntitySignals(
                    product_names=[EntitySpan(text="cd19")],
                )
            ),
        )
    )

    resolved = resolve_object_state(bundle, extract_object_bundle(bundle))

    assert len(resolved.ambiguous_sets) == 1
    ambiguous = resolved.ambiguous_sets[0]
    assert ambiguous.ambiguity_kind == "target_antigen"
    assert ambiguous.clarification_focus == "product_family"
    assert ambiguous.suggested_disambiguation_fields == [
        "business_line",
        "canonical_value",
    ]
    assert ambiguous.resolution_strategy == "clarify_product_family"


def test_product_species_constraint_uses_product_metadata():
    candidate = ObjectCandidate(
        object_type="product",
        display_name="Anti-CD3 antibody",
        canonical_value="Anti-CD3 antibody",
        metadata={"species_reactivity_text": "Human"},
    )

    assert candidate_matches_constraint(candidate, _constraint("species", "human")) is True


def test_service_species_constraint_does_not_reuse_product_style_matching():
    candidate = ObjectCandidate(
        object_type="service",
        display_name="Human Monoclonal Antibodies",
        canonical_value="Human Monoclonal Antibodies",
        business_line="antibody",
        metadata={
            "service_line": "Antibody Services",
            "subcategory": "Monoclonal",
            "page_title": "Human Monoclonal Antibodies",
        },
    )

    assert candidate_matches_constraint(candidate, _constraint("species", "human")) is False


# ---------------------------------------------------------------------------
# v3: Phase-aware resolution
# ---------------------------------------------------------------------------

def test_fresh_start_blocks_context_reuse():
    """On fresh_start, context objects should not be reused even if reference signals allow it."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                is_context_dependent=True,
                reference_mode="active",
            ),
        ),
    )
    recent = [_scored_ref("Some Product", "P00001", salience=0.8)]

    resolved = resolve_objects(bundle, trajectory_phase="fresh_start", recent_objects=recent)

    assert resolved.primary_object is None
    assert resolved.resolution_phase == "unresolved"


def test_follow_up_allows_context_reuse():
    """On follow_up, context objects should be reused when reference signals support it."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                is_context_dependent=True,
                reference_mode="active",
            ),
        ),
    )
    recent = [_scored_ref("Some Product", "P00001", salience=0.8)]

    resolved = resolve_objects(bundle, trajectory_phase="follow_up", recent_objects=recent)

    assert resolved.primary_object is not None
    assert resolved.primary_object.display_name == "Some Product"
    assert resolved.resolution_phase == "context_reuse"


def test_topic_switch_demotes_context_candidates():
    """On topic_switch, context candidates get confidence penalty and context reuse is blocked."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            reference_signals=ReferenceSignals(
                is_context_dependent=True,
                reference_mode="active",
            ),
        ),
    )
    recent = [_scored_ref("Some Product", "P00001", salience=0.8)]

    resolved = resolve_objects(bundle, trajectory_phase="topic_switch", recent_objects=recent)

    # topic_switch blocks context reuse
    assert resolved.primary_object is None
    assert resolved.resolution_phase == "unresolved"


def test_resolution_phase_current_turn():
    """When a current-turn candidate wins, resolution_phase should be 'current_turn'."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                entities=ParserEntitySignals(
                    service_names=[EntitySpan(text="Flow Cytometry")],
                )
            ),
        )
    )

    resolved = resolve_object_state(bundle, extract_object_bundle(bundle))

    assert resolved.primary_object is not None
    assert resolved.resolution_phase == "current_turn"


# ---------------------------------------------------------------------------
# v3: active_object decoupled from primary_object
# ---------------------------------------------------------------------------

def test_active_object_from_memory_when_no_primary():
    """When no primary_object is resolved, active_object should come from memory recent_objects."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(),
    )
    recent = [
        _scored_ref("Anti-CD3 Antibody", "P00042", salience=0.8),
        _scored_ref("Anti-CD19 Antibody", "P00051", salience=0.4),
    ]

    resolved = resolve_objects(bundle, recent_objects=recent)

    assert resolved.primary_object is None
    assert resolved.active_object is not None
    assert resolved.active_object.display_name == "Anti-CD3 Antibody"
    assert resolved.active_object.identifier == "P00042"


def test_active_object_equals_primary_when_primary_exists():
    """When primary_object exists, active_object should equal primary_object."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(
            parser_signals=ParserSignals(
                entities=ParserEntitySignals(
                    service_names=[EntitySpan(text="Flow Cytometry")],
                )
            ),
        )
    )
    recent = [
        _scored_ref("Anti-CD3 Antibody", "P00042", salience=0.8),
    ]

    resolved = resolve_objects(bundle, recent_objects=recent)

    assert resolved.primary_object is not None
    assert resolved.active_object == resolved.primary_object


def test_active_object_none_when_no_primary_and_no_memory():
    """When no primary and no memory context, active_object should be None."""
    bundle = IngestionBundle(
        turn_signals=TurnSignals(),
    )

    resolved = resolve_objects(bundle)

    assert resolved.primary_object is None
    assert resolved.active_object is None
