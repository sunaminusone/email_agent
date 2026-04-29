from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.models import AttributeConstraint, SourceAttribution
from src.objects.constraint_matching import candidate_matches_constraint
from src.objects.models import ObjectCandidate


def _constraint(attribute: str, value: str) -> AttributeConstraint:
    return AttributeConstraint(
        attribute=attribute,
        value=value,
        attribution=SourceAttribution(source_type="parser", recency="CURRENT_TURN"),
    )


def _product(metadata: dict) -> ObjectCandidate:
    return ObjectCandidate(
        object_type="product",
        display_name="Anti-CD19 antibody",
        canonical_value="Anti-CD19 antibody",
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Isotype: exact match (no substring leakage)
# ---------------------------------------------------------------------------

def test_isotype_constraint_matches_exact_value():
    candidate = _product({"isotype": "IgG2a"})
    assert candidate_matches_constraint(candidate, _constraint("isotype", "IgG2a")) is True


def test_isotype_constraint_does_not_match_sibling_subclass():
    """IgG1 user filter must NOT match an IgG2a candidate (substring would leak)."""
    candidate = _product({"isotype": "IgG2a"})
    assert candidate_matches_constraint(candidate, _constraint("isotype", "IgG1")) is False


def test_isotype_constraint_does_not_overmatch_bare_igg_against_igg1():
    """User saying IgG (bare) should NOT exact-match IgG1 candidate.

    PR2 design: isotype uses exact_only — substring would have made
    'IgG' filter accept every IgG-numbered candidate, hiding precision."""
    candidate = _product({"isotype": "IgG1"})
    assert candidate_matches_constraint(candidate, _constraint("isotype", "IgG")) is False


def test_isotype_constraint_matches_composite_form():
    candidate = _product({"isotype": "IgG1/kappa"})
    assert candidate_matches_constraint(candidate, _constraint("isotype", "IgG1/kappa")) is True


def test_isotype_constraint_falls_back_to_ig_class_field():
    candidate = _product({"isotype": "", "ig_class": "IgG"})
    assert candidate_matches_constraint(candidate, _constraint("isotype", "IgG")) is True


# ---------------------------------------------------------------------------
# Costim domain: exact match (composite values must not leak)
# ---------------------------------------------------------------------------

def test_costim_domain_constraint_matches_exact_value():
    candidate = _product({"costimulatory_domain": "4-1BB"})
    assert candidate_matches_constraint(candidate, _constraint("costim_domain", "4-1BB")) is True


def test_costim_domain_constraint_does_not_match_composite_when_user_only_said_4_1bb():
    """User filter '4-1BB' should NOT match a CD28+4-1BB candidate.

    Substring would have leaked because '4 1bb' is contained in 'cd28+4 1bb'."""
    candidate = _product({"costimulatory_domain": "CD28+4-1BB"})
    assert candidate_matches_constraint(candidate, _constraint("costim_domain", "4-1BB")) is False


def test_costim_domain_composite_constraint_matches_composite_candidate():
    candidate = _product({"costimulatory_domain": "CD28+4-1BB"})
    assert candidate_matches_constraint(candidate, _constraint("costim_domain", "CD28+4-1BB")) is True


# ---------------------------------------------------------------------------
# CAR-T group: exact match
# ---------------------------------------------------------------------------

def test_car_t_group_constraint_matches_exact_value():
    candidate = _product({"group_name": "CAR-T Cells"})
    assert candidate_matches_constraint(candidate, _constraint("car_t_group", "CAR-T Cells")) is True


def test_car_t_group_constraint_does_not_overmatch_target_cells_against_car_t_cells():
    """'Engineered CAR-T Target Cells' filter should not match 'CAR-T Cells'."""
    candidate = _product({"group_name": "CAR-T Cells"})
    assert (
        candidate_matches_constraint(
            candidate,
            _constraint("car_t_group", "Engineered CAR-T Target Cells"),
        )
        is False
    )


# ---------------------------------------------------------------------------
# Regression: existing dimensions still substring-match
# ---------------------------------------------------------------------------

def test_species_constraint_still_substring_matches_for_legacy_dimensions():
    """species was substring-matching before PR2; keep that behavior."""
    candidate = _product({"species_reactivity_text": "Human, Mouse"})
    assert candidate_matches_constraint(candidate, _constraint("species", "human")) is True


def test_application_constraint_still_substring_matches():
    candidate = _product({"application_text": "ELISA, WB, IHC"})
    assert (
        candidate_matches_constraint(
            candidate,
            _constraint("application or validation", "elisa"),
        )
        is True
    )
