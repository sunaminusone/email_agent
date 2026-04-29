from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from src.ingestion.entity_to_constraint import (
    _normalize_car_t_group,
    _normalize_costim,
    _normalize_isotype,
    entities_to_attribute_constraints,
)
from src.ingestion.models import EntitySpan, ParserEntitySignals


def _span(text: str) -> EntitySpan:
    return EntitySpan(text=text, raw=text)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("IgG1", "IgG1"),
        ("igg1", "IgG1"),
        ("Mouse IgG1", "IgG1"),
        ("Rabbit IgG", "IgG"),
        ("IgG2a", "IgG2a"),
        ("IgG2b", "IgG2b"),
        ("IgG kappa", "IgG/kappa"),
        ("IgG1 kappa", "IgG1/kappa"),
        ("IgG1/kappa", "IgG1/kappa"),
        ("IgG1, lambda", "IgG1/lambda"),
        ("IgG1, κ", "IgG1/kappa"),
        ("IgM", "IgM"),
        ("Mouse IgA", "IgA"),
        ("Acme antibody", ""),
        ("", ""),
        ("F", ""),
    ],
)
def test_normalize_isotype(raw, expected):
    assert _normalize_isotype(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("CD28", "CD28"),
        ("cd28", "CD28"),
        ("4-1BB", "4-1BB"),
        ("4 1BB", "4-1BB"),
        ("41BB", "4-1BB"),
        ("CD28+4-1BB", "CD28+4-1BB"),
        ("CD28/4-1BB", "CD28+4-1BB"),
        ("CD28-4-1BB", "CD28+4-1BB"),
        ("CD28 and 4-1BB", "CD28+4-1BB"),
        ("with 4-1BB", "4-1BB"),
        ("the CD28", "CD28"),
        ("GITR", "GITR"),
        ("OX40", ""),
        ("", ""),
    ],
)
def test_normalize_costim(raw, expected):
    assert _normalize_costim(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("CAR-T Cells", "CAR-T Cells"),
        ("car-t cells", "CAR-T Cells"),
        ("car t cell", "CAR-T Cells"),
        ("Engineered CAR-T Target Cells", "Engineered CAR-T Target Cells"),
        ("target cells", "Engineered CAR-T Target Cells"),
        ("Non-Transduced T Cells", "Non-Transduced T Cells"),
        ("untransduced T cells", "Non-Transduced T Cells"),
        ("CAR Detection Probes", "CAR Detection Probes"),
        ("detection probes", "CAR Detection Probes"),
        ("activation beads", "Cell Media and Activation Beads"),
        ("Non-Transduced Macrophages", "Non-Transduced Macrophages"),
        ("Stem Cells", ""),
        ("", ""),
    ],
)
def test_normalize_car_t_group(raw, expected):
    assert _normalize_car_t_group(raw) == expected


def test_bridge_emits_constraints_for_recognized_entities():
    entities = ParserEntitySignals(
        isotypes=[_span("IgG2a")],
        costim_domains=[_span("4-1BB")],
        car_t_groups=[_span("target cells")],
    )
    constraints = entities_to_attribute_constraints(entities)
    by_attr = {c.attribute: c for c in constraints}
    assert by_attr["isotype"].value == "IgG2a"
    assert by_attr["costim_domain"].value == "4-1BB"
    assert by_attr["car_t_group"].value == "Engineered CAR-T Target Cells"
    assert len(constraints) == 3


def test_bridge_drops_unrecognized_entities():
    entities = ParserEntitySignals(
        isotypes=[_span("Acme antibody")],
        costim_domains=[_span("OX40")],
        car_t_groups=[_span("Stem Cells")],
    )
    assert entities_to_attribute_constraints(entities) == []


def test_bridge_dedupes_repeated_canonical_values():
    entities = ParserEntitySignals(
        isotypes=[_span("IgG2a"), _span("Mouse IgG2a"), _span("igg2a")],
    )
    constraints = entities_to_attribute_constraints(entities)
    assert len(constraints) == 1
    assert constraints[0].value == "IgG2a"


def test_bridge_preserves_raw_text_in_constraint():
    entities = ParserEntitySignals(
        isotypes=[_span("Mouse IgG1")],
    )
    constraints = entities_to_attribute_constraints(entities)
    assert constraints[0].raw == "Mouse IgG1"
    assert constraints[0].value == "IgG1"
    assert constraints[0].operator == "equals"


def test_bridge_empty_entities_returns_empty():
    assert entities_to_attribute_constraints(ParserEntitySignals()) == []
