from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.selection import run_catalog_selection


def test_run_catalog_selection_falls_back_to_local_registry_when_driver_missing(monkeypatch):
    monkeypatch.setattr("src.catalog.selection.psycopg", None)

    result = run_catalog_selection(
        query="product information for catalog number P06329",
        catalog_numbers=["P06329"],
        top_k=5,
    )

    assert result["match_status"] == "matched"
    assert result["lookup_mode"] == "local_registry_fallback"
    assert result["matches"]
    top_match = result["matches"][0]
    assert top_match["catalog_no"] == "P06329"
    assert top_match["name"] == "Rabbit Polyclonal antibody to MSH2"
    assert top_match["target_antigen"] == "MSH2"
    assert top_match["application_text"] == "ELISA, WB, IHC"
    assert top_match["species_reactivity_text"] == "Human, Mouse"


def test_run_catalog_selection_seeds_exact_lookup_from_unique_registry_alias():
    result = run_catalog_selection(
        query="Tell me about NPM1",
        product_names=["Mouse Monoclonal antibody to Nucleophosmin"],
        top_k=5,
    )

    assert result["match_status"] == "matched"
    assert result["retrieval_tier"] == "tier_1"
    assert result["catalog_numbers"] == ["20001"]
    assert result["matches"]
    top_match = result["matches"][0]
    assert top_match["catalog_no"] == "20001"


def test_run_catalog_selection_uses_tier_three_when_parser_has_no_entity_scope():
    result = run_catalog_selection(
        query="Do you have something for nucleophosmin?",
        product_names=[],
        service_names=[],
        targets=[],
        top_k=5,
    )

    assert result["retrieval_tier"] == "tier_3"


def test_run_catalog_selection_uses_tier_two_for_structured_but_non_exact_product_scope():
    result = run_catalog_selection(
        query="Tell me about MSH2",
        product_names=["MSH2"],
        top_k=5,
    )

    assert result["retrieval_tier"] in {"tier_2", "tier_1"}
    assert result["match_status"] == "matched"
