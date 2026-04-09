from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.selector import select_commercial_tools


def test_active_service_follow_up_selects_technical_rag():
    tools = select_commercial_tools(
        {
            "query": "What models do you support?",
            "context": {"primary_intent": "follow_up", "secondary_intents": []},
            "entities": {},
            "request_flags": {},
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

    assert "technical_rag" in tools
    assert "product_lookup" not in tools


def test_current_turn_entity_scope_blocks_active_service_fallback():
    tools = select_commercial_tools(
        {
            "query": "What applications do you support?",
            "context": {"primary_intent": "follow_up", "secondary_intents": []},
            "entities": {
                "product_names": ["Mouse Monoclonal antibody to Nucleophosmin"],
            },
            "request_flags": {},
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

    assert "technical_rag" not in tools
    assert "product_lookup" in tools


def test_non_technical_follow_up_does_not_use_active_service_fallback():
    tools = select_commercial_tools(
        {
            "query": "Send me the brochure",
            "context": {"primary_intent": "follow_up", "secondary_intents": []},
            "entities": {},
            "request_flags": {"needs_documentation": True},
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

    assert "technical_rag" not in tools
    assert "documentation_lookup" in tools
