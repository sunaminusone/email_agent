from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.retrieval.shared import candidate_aliases
from src.catalog.normalization import select_search_term


def test_candidate_aliases_do_not_include_query_filler_when_product_name_is_present():
    aliases = candidate_aliases(
        query="Tell me about NPM1",
        product_names=["Mouse Monoclonal antibody to Nucleophosmin"],
        service_names=[],
        targets=[],
    )

    assert "mouse monoclonal antibody to nucleophosmin" in aliases
    assert "me" not in aliases
    assert "about" not in aliases
    assert "tell" not in aliases


def test_candidate_aliases_keep_explicit_product_name_whole_without_token_expansion():
    aliases = candidate_aliases(
        query="Tell me about NPM1",
        product_names=["Mouse Monoclonal antibody to Nucleophosmin"],
        service_names=[],
        targets=[],
    )

    assert aliases == ["mouse monoclonal antibody to nucleophosmin"]


def test_select_search_term_prefers_scoped_product_name_over_query_filler():
    token = select_search_term(
        query="Tell me about NPM1",
        product_names=["Mouse Monoclonal antibody to Nucleophosmin"],
        service_names=[],
        targets=[],
    )

    assert token == "nucleophosmin"
