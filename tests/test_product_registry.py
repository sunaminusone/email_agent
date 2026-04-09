from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.product_registry import (
    canonicalize_product_name,
    get_product_registry_payload,
    lookup_product_by_catalog_no,
    lookup_products_by_alias,
)


def test_product_registry_contains_known_antibody_aliases():
    matches = lookup_products_by_alias("NPM1")
    assert matches
    assert any(match["catalog_no"] == "20001" for match in matches)
    assert any("Mouse Monoclonal antibody to Nucleophosmin" == match["canonical_name"] for match in matches)


def test_product_registry_contains_known_polyclonal_aliases():
    matches = lookup_products_by_alias("6 His epitope tag")
    assert matches
    assert any(match["catalog_no"] == "P00002" for match in matches)


def test_product_registry_generates_cart_name_when_source_name_missing():
    match = lookup_product_by_catalog_no("PM-CAR1000")
    assert match is not None
    assert match["canonical_name"] == "Mock CD28 CAR-T"
    assert "Mock" in match["aliases"]
    assert "CAR-T Cells" in match["aliases"]


def test_product_registry_contains_mrna_products():
    match = lookup_product_by_catalog_no("PM-LNP-0010")
    assert match is not None
    assert match["canonical_name"] == "COVID-19 Spike Protein (Alpha Variant) mRNA-LNP"
    assert match["business_line"] == "mrna_lnp"


def test_product_registry_includes_mrna_lipid_nanoparticle_alias():
    matches = lookup_products_by_alias("mRNA-Lipid Nanoparticle")
    assert matches
    assert any(match["catalog_no"] == "PM-LNP-0010" for match in matches)


def test_product_registry_payload_exposes_alias_index():
    payload = get_product_registry_payload()
    assert "by_catalog_no" in payload
    assert "alias_to_catalog_nos" in payload
    assert "npm1" in payload["alias_to_catalog_nos"]


def test_product_registry_normalizes_his_tag_variants():
    matches = lookup_products_by_alias("6xHis epitope tag")
    assert matches
    assert any(match["catalog_no"] == "P00002" for match in matches)

    matches = lookup_products_by_alias("6×His epitope tag")
    assert matches
    assert any(match["catalog_no"] == "P00002" for match in matches)


def test_product_registry_treats_tp53_as_ambiguous_alias():
    matches = lookup_products_by_alias("TP53")
    assert len(matches) >= 3
    assert any(match["catalog_no"] == "20338" for match in matches)
    assert any(match["catalog_no"] == "P00072" for match in matches)
    assert canonicalize_product_name("TP53") == "TP53"


def test_product_registry_exposes_antibody_metadata():
    match = lookup_product_by_catalog_no("P06329")
    assert match is not None
    assert match["target_antigen"] == "MSH2"
    assert match["application_text"] == "ELISA, WB, IHC"
    assert match["species_reactivity_text"] == "Human, Mouse"
