from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.conversation.context_scope import (
    has_current_scope,
    is_service_scoped_follow_up,
    query_has_product_scope_marker,
    query_matches_non_technical_fallback_path,
    query_has_service_scope_marker,
    resolve_effective_scope,
    should_fallback_to_active_service_context,
)


def test_service_scope_markers_support_singular_and_plural_forms():
    assert query_has_service_scope_marker("What phase is next?")
    assert query_has_service_scope_marker("What phases are included?")
    assert query_has_service_scope_marker("Which application is supported?")
    assert query_has_service_scope_marker("Which applications are supported?")
    assert query_has_product_scope_marker("Which applications are supported?")
    assert query_has_product_scope_marker("What species is this validated for?")


def test_service_scoped_follow_up_requires_active_service_name():
    assert is_service_scoped_follow_up("What models do you support?", "mRNA-LNP Gene Delivery")
    assert not is_service_scoped_follow_up("What models do you support?", "")


def test_active_service_fallback_requires_continuity_service_context_and_no_current_scope():
    assert should_fallback_to_active_service_context(
        query="What phases are included?",
        active_service_name="mRNA-LNP Gene Delivery",
        active_entity_kind="service",
        turn_type="follow_up",
        has_current_scope=False,
    )
    assert not should_fallback_to_active_service_context(
        query="What phases are included?",
        active_service_name="mRNA-LNP Gene Delivery",
        active_entity_kind="service",
        turn_type="fresh_request",
        has_current_scope=False,
    )
    assert not should_fallback_to_active_service_context(
        query="What phases are included?",
        active_service_name="mRNA-LNP Gene Delivery",
        active_entity_kind="product",
        turn_type="follow_up",
        has_current_scope=False,
    )
    assert not should_fallback_to_active_service_context(
        query="What phases are included?",
        active_service_name="mRNA-LNP Gene Delivery",
        active_entity_kind="service",
        turn_type="follow_up",
        has_current_scope=True,
    )


def test_non_technical_follow_up_paths_are_excluded_from_active_service_fallback():
    assert query_matches_non_technical_fallback_path("Send me the brochure")
    assert query_matches_non_technical_fallback_path("What is the shipping ETA?")
    assert query_matches_non_technical_fallback_path("Connect me to support")
    assert not should_fallback_to_active_service_context(
        query="Send me the brochure",
        active_service_name="mRNA-LNP Gene Delivery",
        active_entity_kind="service",
        turn_type="follow_up",
        has_current_scope=False,
    )


def test_resolve_effective_scope_prefers_current_target_over_active_service():
    resolved = resolve_effective_scope(
        {
            "query": "What applications do you support?",
            "entities": {
                "targets": ["Nucleophosmin"],
            },
            "product_lookup_keys": {},
            "active_service_name": "mRNA-LNP Gene Delivery",
            "session_payload": {
                "active_entity": {
                    "entity_kind": "service",
                }
            },
            "turn_resolution": {
                "turn_type": "follow_up",
            },
        }
    )

    assert resolved["scope_type"] == "scientific_target"
    assert resolved["source"] == "current"
    assert resolved["name"] == "Nucleophosmin"
    assert resolved["reason"] == "current_scientific_target_scope"


def test_has_current_scope_treats_target_as_current_scope():
    assert has_current_scope(
        {
            "entities": {
                "targets": ["Nucleophosmin"],
            },
            "product_lookup_keys": {},
        }
    )


def test_resolve_effective_scope_can_preserve_active_product_scope():
    resolved = resolve_effective_scope(
        {
            "query": "What applications do you support?",
            "entities": {},
            "product_lookup_keys": {},
            "active_product_name": "Mouse Monoclonal antibody to Nucleophosmin",
            "session_payload": {
                "active_product_name": "Mouse Monoclonal antibody to Nucleophosmin",
                "active_entity": {
                    "entity_kind": "product",
                },
            },
            "turn_resolution": {
                "turn_type": "follow_up",
            },
        }
    )

    assert resolved["scope_type"] == "product"
    assert resolved["source"] == "active"
    assert resolved["name"] == "Mouse Monoclonal antibody to Nucleophosmin"
    assert resolved["reason"] == "active_product_follow_up_matched_product_scope_markers"
