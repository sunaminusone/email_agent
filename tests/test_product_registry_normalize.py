from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from src.objects.registries.product_registry import (
    _normalize_application_tokens,
    _normalize_isotype,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Mouse IgG1", "IgG1"),
        ("Mouse  IgG1", "IgG1"),                # double-space (166 rows in real Excel)
        ("mouse IgG1", "IgG1"),                 # lowercased prefix
        ("Mouse IGg1", "IgG1"),                 # casing typo
        ("Mouse IgG2b", "IgG2b"),
        ("Mouse IgG2a", "IgG2a"),
        ("Mouse Ig M", "IgM"),                  # space inside Ig M
        ("Mouse IgG", "IgG"),                   # bare IgG
        ("Mouse IgG3", "IgG3"),
        ("Mouse IgG1,kappa", "IgG1/kappa"),
        ("Mouse IgG1,κ", "IgG1/kappa"),         # greek kappa
        ("Mouse IgG1.kappa", "IgG1/kappa"),
        ("Mouse IgG2b/Mouse IgG2a", "IgG_mixed"),
        ("Mouse IgG1/Mouse IgG2b", "IgG_mixed"),
        ("Rat Mab", ""),                        # heavy chain not present, drop
        ("F", ""),                              # Excel data error
        ("0", ""),                              # numeric Excel cell
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_isotype(raw, expected):
    assert _normalize_isotype(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ELISA,WB+,IHC+", ("ELISA", "WB", "IHC")),
        ("ELISA,FCM", ("ELISA", "FCM")),
        ("ELISA,WB,IHC,ICC,FCM", ("ELISA", "WB", "IHC", "ICC", "FCM")),
        ("ELISAFCM", ("ELISA", "FCM")),         # missing comma adjoined
        ("WB/IHC", ("WB", "IHC")),
        ("flow cytometry", ("FCM",)),
        ("western blot, ELISA", ("WB", "ELISA")),
        ("ELISA, IF", ("ELISA", "IF")),
        ("ihc-p", ("IHC",)),                    # IHC variant
        ("FACS", ("FCM",)),                     # synonym
        ("FCM弱", ("FCM",)),                    # noise suffix dropped
        ("", ()),
        (None, ()),
    ],
)
def test_normalize_application_tokens(raw, expected):
    assert _normalize_application_tokens(raw) == expected


def test_normalize_application_tokens_dedupes():
    """Repeated tokens collapse to a single canonical entry."""
    assert _normalize_application_tokens("ELISA,ELISA,WB,WB") == ("ELISA", "WB")
