"""Regression tests for ``extract_catalog_numbers`` regex stack.

The catalog regex stack in `src/catalog/normalization.py:CATALOG_NUMBER_PATTERNS`
runs alongside the (separately tested) regex stack in
`src/ingestion/deterministic_signals.py`. The deterministic_signals one was
tightened in commit 2c5922c; this file pins down the equivalent tightening
on the normalization side so a future loosening surfaces as a test failure
rather than as silent bogus catalog candidates flowing into
`src/catalog/selection.py:run_catalog_selection`.

Closes tools-audit backlog #6.5.
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalog.normalization import extract_catalog_numbers


# ---------------------------------------------------------------------------
# Positive — these MUST be extracted (real catalog shapes)
# ---------------------------------------------------------------------------


def test_extracts_five_digit_catalog_no() -> None:
    assert "10007" in extract_catalog_numbers("Please quote catalog 10007")


def test_extracts_pm_car_sku() -> None:
    assert "PM-CAR1000" in extract_catalog_numbers("info on PM-CAR1000")


def test_extracts_pm_lnp_sku() -> None:
    assert "PM-LNP-0010" in extract_catalog_numbers("spec sheet for PM-LNP-0010")


def test_extracts_case_insensitive_pm_prefix() -> None:
    # Real catalog_no's are upper-case canonical, but customer emails are
    # often lower / mixed. Extraction normalizes to upper-case.
    assert "PM-CAR1000" in extract_catalog_numbers("info on pm-car1000")
    assert "PM-LNP-0010" in extract_catalog_numbers("Pm-Lnp-0010 please")


def test_extracts_multiple_in_one_query() -> None:
    out = extract_catalog_numbers("compare PM-CAR1000 and PM-CAR1042")
    assert "PM-CAR1000" in out
    assert "PM-CAR1042" in out


def test_dedupes_repeats() -> None:
    out = extract_catalog_numbers("PM-CAR1000 PM-CAR1000 PM-CAR1000")
    assert out.count("PM-CAR1000") == 1


# ---------------------------------------------------------------------------
# Negative — these MUST NOT extract (natural-language compounds 2c5922c
# tightened in deterministic_signals.py; the same shapes must be rejected
# here too, or catalog/selection.py:218 propagates bogus catalog candidates)
# ---------------------------------------------------------------------------


def test_rejects_pre_tested_compound() -> None:
    assert extract_catalog_numbers("looking for PRE-TESTED formulations") == []


def test_rejects_car_cells_compound() -> None:
    assert extract_catalog_numbers("Since you offer both CAR-CELLS and a virus production service") == []


def test_rejects_non_profit() -> None:
    assert extract_catalog_numbers("we are a non-profit lab") == []


def test_rejects_mrna_lnp_business_line_token() -> None:
    # "mRNA-LNP" is the business-line label, not a catalog_no. Customer
    # emails mention it freely.
    assert extract_catalog_numbers("interested in your mRNA-LNP services") == []


def test_rejects_anti_cd_compounds_without_digit_neighbor() -> None:
    # "anti-CD" alone has no digit; the catalog regex used to capture
    # generic anti-XYZ tokens.
    assert extract_catalog_numbers("anti-HLA antibody panel") == []


def test_rejects_simple_word_with_hyphen() -> None:
    # "follow-up" / "long-term" / "high-throughput" — all should be
    # invisible to the catalog regex.
    assert extract_catalog_numbers("a follow-up on the long-term high-throughput study") == []


# ---------------------------------------------------------------------------
# Mixed — extracts the real SKU from a query that also contains noise
# ---------------------------------------------------------------------------


def test_extracts_real_sku_alongside_noise() -> None:
    out = extract_catalog_numbers("Send me info on PM-CAR1000 PRE-TESTED formulations")
    assert "PM-CAR1000" in out
    assert "PRE-TESTED" not in out


def test_extracts_numeric_sku_alongside_noise() -> None:
    out = extract_catalog_numbers("catalog 20081 (we are a non-profit)")
    assert "20081" in out
    assert "NON-PROFIT" not in out
