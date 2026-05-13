"""Per-tool drafting fragments — conditionally loaded into the system
prompt by ``draft_llm._build_system_prompt`` based on which tools fired.

Pattern: each fragment is a markdown file in this directory; the module-
level ``_FRAGMENTS`` table maps a *trigger set* of tool names → loaded
text. A fragment is appended to the system prompt iff at least one of
its trigger tools fired in the current turn.

Contract: ``docs/RESPONDER_DESIGN_V4.md`` ⭐ section + "Drafting fragments".
"""
from __future__ import annotations

from pathlib import Path


_FRAGMENTS_DIR = Path(__file__).parent


def _load(file_name: str) -> str:
    return (_FRAGMENTS_DIR / file_name).read_text(encoding="utf-8").strip()


# (trigger_tools, fragment_text). Order is the load order (stable for
# reproducible prompts). Single-tool fragments use a one-element set;
# fragments that apply across tools (e.g. drafting nuance that spans
# catalog/pricing/QB record shapes) use a multi-tool set.
_FRAGMENTS: list[tuple[frozenset[str], str]] = [
    (
        frozenset({"catalog_lookup_tool", "pricing_lookup_tool"}),
        _load("catalog_record.md"),
    ),
    (
        frozenset({
            "invoice_lookup_tool",
            "order_lookup_tool",
            "shipping_lookup_tool",
            "customer_lookup_tool",
        }),
        _load("operational_record.md"),
    ),
    (
        frozenset({"document_lookup_tool"}),
        _load("document_link_rendering.md"),
    ),
    (
        frozenset({"pricing_lookup_tool"}),
        _load("pricing_semantics.md"),
    ),
    (
        frozenset({
            "catalog_lookup_tool",
            "pricing_lookup_tool",
            "invoice_lookup_tool",
            "order_lookup_tool",
            "shipping_lookup_tool",
            "customer_lookup_tool",
        }),
        _load("record_gap_followup.md"),
    ),
]


def fragments_for_tools(fired_tool_names: set[str]) -> list[str]:
    """Return drafting fragments for the tools that fired this turn, in
    stable definition order. A fragment loads iff its trigger set
    intersects fired_tool_names."""
    return [text for trigger, text in _FRAGMENTS if trigger & fired_tool_names]


__all__ = ["fragments_for_tools"]
