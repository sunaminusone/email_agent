from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.models import ParserSignals
from src.ingestion.reference_signals import (
    detect_reference_mode,
    extract_reference_attribute_constraints,
    extract_reference_signals,
)
from src.memory.models import ClarificationMemory, MemoryContext, MemorySnapshot


def test_pronoun_reference_mode_maps_to_active():
    assert detect_reference_mode("What about its datasheet?") == "active"
    assert detect_reference_mode("Can you compare them?") == "active"


def test_specific_reference_modes_still_win_over_pronouns():
    assert detect_reference_mode("Compare the other one with it") == "other"
    assert detect_reference_mode("Tell me about both of them") == "all"


def test_extract_reference_signals_marks_pronoun_turn_as_active():
    signals = extract_reference_signals(
        "What about its datasheet?",
        parser_signals=ParserSignals(),
    )

    assert signals.reference_mode == "active"
    assert signals.is_context_dependent is True
    assert signals.requires_active_context_for_safe_resolution is True


def test_extract_reference_signals_can_source_recent_context_from_memory_context():
    memory_context = MemoryContext(
        snapshot=MemorySnapshot(
            clarification_memory=ClarificationMemory(
                pending_clarification_type="product_selection",
                pending_candidate_options=["A100", "A101"],
            )
        ),
        recent_objects_by_relevance=[],
    )
    signals = extract_reference_signals(
        "Compare the other one",
        parser_signals=ParserSignals(),
        memory_context=memory_context,
    )

    assert signals.reference_mode == "other"
    assert signals.requires_active_context_for_safe_resolution is False


def test_extract_reference_attribute_constraints_supports_documented_forms():
    numeric = extract_reference_attribute_constraints("I want the 100ul one")
    multiword = extract_reference_attribute_constraints("I want the rabbit monoclonal one")
    hyphenated = extract_reference_attribute_constraints("I want the IHC-validated one")

    assert [(constraint.attribute, constraint.value) for constraint in numeric] == [("format_or_size", "100ul")]
    assert [(constraint.attribute, constraint.value) for constraint in multiword] == [
        ("species", "rabbit"),
        ("clonality", "monoclonal"),
    ]
    assert [(constraint.attribute, constraint.value) for constraint in hyphenated] == [
        ("application_or_validation", "ihc-validated")
    ]


def test_extract_reference_attribute_constraints_still_ignores_mode_words():
    constraints = extract_reference_attribute_constraints("Compare the other one and the first one")

    assert constraints == []


def test_extract_reference_attribute_constraints_can_split_multiple_filters():
    constraints = extract_reference_attribute_constraints("I want the rabbit IHC-validated 100ul one")

    assert [(constraint.attribute, constraint.value) for constraint in constraints] == [
        ("format_or_size", "100ul"),
        ("species", "rabbit"),
        ("application_or_validation", "ihc-validated"),
    ]


def test_extract_reference_attribute_constraints_falls_back_to_descriptive_filter():
    constraints = extract_reference_attribute_constraints("I want the green one")

    assert [(constraint.attribute, constraint.value) for constraint in constraints] == [
        ("descriptive_filter", "green")
    ]
