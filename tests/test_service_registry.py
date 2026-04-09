from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.conversation.service_registry import (
    canonicalize_service_name,
    get_service_registry_payload,
    lookup_services_by_alias,
)


def test_service_registry_loads_known_service_names():
    payload = get_service_registry_payload()
    assert "mRNA-LNP Gene Delivery" in payload["by_canonical_name"]
    assert "Mouse Monoclonal Antibodies" in payload["by_canonical_name"]


def test_service_registry_matches_manual_alias_for_mrna_lnp():
    matches = lookup_services_by_alias("mRNA LNP Gene Delivery")
    assert matches
    assert matches[0]["canonical_name"] == "mRNA-LNP Gene Delivery"


def test_service_registry_canonicalizes_mrna_lnp_delivery_alias():
    assert canonicalize_service_name("mRNA-LNP delivery") == "mRNA-LNP Gene Delivery"


def test_service_registry_handles_ampersand_normalization():
    assert canonicalize_service_name("Affinity Tune-Up and Humanization") == "Affinity Tune-Up & Humanization"
