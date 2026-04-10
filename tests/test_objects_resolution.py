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
    ValueSignal,
)
from src.objects.constraint_matching import candidate_matches_constraint
from src.objects.extraction import extract_object_bundle
from src.objects.models import ObjectCandidate
from src.objects.resolution import resolve_object_state


def _constraint(attribute: str, value: str) -> AttributeConstraint:
    return AttributeConstraint(
        attribute=attribute,
        value=value,
        attribution=SourceAttribution(source_type="deterministic", recency="CURRENT_TURN"),
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
        stateful_anchors=StatefulAnchors(
            active_entity_kind=ValueSignal(value="product"),
            active_entity_identifier=ValueSignal(value="P00001"),
            active_entity_display_name=ValueSignal(value="Rabbit Polyclonal antibody to ACTB"),
        ),
    )

    resolved = resolve_object_state(bundle, extract_object_bundle(bundle))

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
