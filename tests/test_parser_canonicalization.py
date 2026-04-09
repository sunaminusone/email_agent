from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.parser.postprocess import postprocess_parsed_result
from src.schemas import ParsedResult


def test_postprocess_canonicalizes_unique_product_alias():
    parsed = ParsedResult()
    parsed.entities.product_names = ["NPM1"]

    result = postprocess_parsed_result(parsed, user_query="Tell me about NPM1")

    assert result.entities.product_names == [
        "Mouse Monoclonal antibody to Nucleophosmin"
    ]


def test_postprocess_leaves_ambiguous_product_alias_unchanged():
    parsed = ParsedResult()
    parsed.entities.product_names = ["mRNA-Lipid Nanoparticle"]

    result = postprocess_parsed_result(
        parsed,
        user_query="Tell me about mRNA-Lipid Nanoparticle",
    )

    assert result.entities.product_names == ["mRNA-Lipid Nanoparticle"]


def test_postprocess_canonicalizes_service_alias():
    parsed = ParsedResult()
    parsed.entities.service_names = ["mRNA-LNP delivery"]

    result = postprocess_parsed_result(
        parsed,
        user_query="Tell me about mRNA-LNP delivery",
    )

    assert result.entities.service_names == ["mRNA-LNP Gene Delivery"]


def test_postprocess_canonicalizes_service_ampersand_alias():
    parsed = ParsedResult()
    parsed.entities.service_names = ["Affinity Tune-Up and Humanization"]

    result = postprocess_parsed_result(
        parsed,
        user_query="Tell me about Affinity Tune-Up and Humanization",
    )

    assert result.entities.service_names == ["Affinity Tune-Up & Humanization"]
