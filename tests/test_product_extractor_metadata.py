from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from src.ingestion.models import EntitySpan, IngestionBundle
from src.objects.extractors import product_extractor


def _span(text: str) -> EntitySpan:
    return EntitySpan(text=text, raw=text)


def _bundle_with_product_span(span_text: str) -> IngestionBundle:
    bundle = IngestionBundle()
    bundle.turn_signals.parser_signals.entities.product_names = [_span(span_text)]
    return bundle


def _make_match(catalog_no: str, **overrides):
    base = {
        "catalog_no": catalog_no,
        "canonical_name": f"Mouse Monoclonal antibody to {catalog_no}",
        "business_line": "antibody",
        "aliases": [],
        "target_antigen": "CD19",
        "application_text": "ELISA,WB,FCM",
        "applications": ["ELISA", "WB", "FCM"],
        "species_reactivity_text": "",
        "format_or_size": "",
        "clone": "",
        "clonality": "monoclonal",
        "isotype": "IgG1",
        "ig_class": "",
        "costimulatory_domain": "",
        "construct": "",
        "group_name": "",
        "marker": "",
    }
    base.update(overrides)
    return base


def test_ambiguous_branch_carries_constraint_relevant_metadata(monkeypatch):
    """Regression: ambiguous candidates must carry isotype/applications/costim/group_name
    so PR2 constraint matchers have something to filter on."""
    matches = [
        _make_match("20100", isotype="IgG1"),
        _make_match("20101", isotype="IgG2a"),
        _make_match("20102", isotype="IgG2b"),
    ]
    monkeypatch.setattr(product_extractor, "lookup_products_by_alias", lambda _: matches)
    monkeypatch.setattr(
        product_extractor,
        "lookup_product_alias_matches",
        lambda _: [{"alias_kind": "target_antigen"} for _ in matches],
    )

    bundle = _bundle_with_product_span("CD19")
    output = product_extractor.extract_product_candidates(bundle)

    assert len(output.ambiguous_sets) == 1
    candidates = output.ambiguous_sets[0].candidates
    assert len(candidates) == 3

    isotypes = [c.metadata["isotype"] for c in candidates]
    assert isotypes == ["IgG1", "IgG2a", "IgG2b"]

    for cand in candidates:
        meta = cand.metadata
        assert "applications" in meta
        assert "costimulatory_domain" in meta
        assert "group_name" in meta
        assert "marker" in meta


def test_resolved_branch_carries_applications_field(monkeypatch):
    match = _make_match("20100")
    monkeypatch.setattr(product_extractor, "lookup_products_by_alias", lambda _: [match])
    monkeypatch.setattr(
        product_extractor,
        "lookup_product_alias_matches",
        lambda _: [{"alias_kind": "target_antigen"}],
    )

    bundle = _bundle_with_product_span("CD19 antibody")
    output = product_extractor.extract_product_candidates(bundle)

    assert len(output.candidates) == 1
    meta = output.candidates[0].metadata
    assert meta["applications"] == ["ELISA", "WB", "FCM"]
    assert meta["isotype"] == "IgG1"
