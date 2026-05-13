from __future__ import annotations

from unittest.mock import patch

from src.rag.query_scope import canonicalize_service_name
from src.rag import service as rag_service


def test_canonicalize_service_name_resolves_manual_alias():
    assert canonicalize_service_name("CAR-T Development") == "CAR-T Cell Design and Development"


def test_canonicalize_service_name_is_case_insensitive():
    assert canonicalize_service_name("car-t development") == "CAR-T Cell Design and Development"
    assert canonicalize_service_name("CUSTOM CAR-T CELL DEVELOPMENT") == "CAR-T Cell Design and Development"


def test_canonicalize_service_name_resolves_auto_phrase_variant():
    assert (
        canonicalize_service_name("Rabbit Polyclonal Antibodies")
        == "Rabbit Polyclonal Antibody Production"
    )


def test_canonicalize_service_name_passes_through_unknown_string():
    assert canonicalize_service_name("antibody discovery") == "antibody discovery"
    assert canonicalize_service_name("nonexistent xyz service") == "nonexistent xyz service"


def test_canonicalize_service_name_handles_empty():
    assert canonicalize_service_name("") == ""
    assert canonicalize_service_name(None) == ""


def test_canonicalize_service_name_is_idempotent_on_canonical_input():
    canonical = "CAR-T Cell Design and Development"
    assert canonicalize_service_name(canonical) == canonical


def test_retrieve_technical_knowledge_canonicalizes_active_service_name_at_entry():
    captured: dict = {}

    def _fake_retrieve_chunks(**kwargs):
        captured["active_service_name"] = kwargs.get("active_service_name", "")
        return {
            "matches": [],
            "retrieval_mode": "fake",
            "query_variants": [],
            "confidence": {},
            "variant_observability": {},
        }

    with patch.object(rag_service, "retrieve_chunks", side_effect=_fake_retrieve_chunks):
        rag_service.retrieve_technical_knowledge(
            query="how does it work?",
            active_service_name="CAR-T Development",
            business_line_hint="car_t",
        )

    assert captured["active_service_name"] == "CAR-T Cell Design and Development"
