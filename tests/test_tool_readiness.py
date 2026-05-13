"""Tests for src.tools.readiness.check_readiness."""
from __future__ import annotations

import pytest

from src.tools.models import ToolCapability
from src.tools.readiness import check_readiness


def _cap(
    tool_name: str = "test_tool",
    full: list[str] | None = None,
    degraded: list[str] | None = None,
) -> ToolCapability:
    return ToolCapability(
        tool_name=tool_name,
        full_identifiers=full or [],
        degraded_identifiers=degraded or [],
    )


# ---------------------------------------------------------------------------
# Full readiness
# ---------------------------------------------------------------------------

class TestFull:
    def test_no_identifiers_always_full(self):
        """Tools with no identifiers (RAG, catalog) are always full."""
        r = check_readiness(_cap(), {"anything": "value"})
        assert r.quality == "full"
        assert r.can_execute is True

    def test_no_identifiers_empty_params_still_full(self):
        r = check_readiness(_cap(), {})
        assert r.quality == "full"
        assert r.can_execute is True

    def test_full_identifier_present(self):
        r = check_readiness(
            _cap(full=["order_number"]),
            {"order_number": "ORD-123"},
        )
        assert r.quality == "full"
        assert r.can_execute is True
        assert r.matched_identifier == "order_number"

    def test_full_identifier_preferred_over_degraded(self):
        """When both full and degraded identifiers are present, full wins."""
        r = check_readiness(
            _cap(full=["order_number"], degraded=["customer_name"]),
            {"order_number": "ORD-1", "customer_name": "Acme"},
        )
        assert r.quality == "full"
        assert r.matched_identifier == "order_number"

    def test_first_full_identifier_wins(self):
        r = check_readiness(
            _cap(full=["tracking_number", "order_number"]),
            {"tracking_number": "TRK-1", "order_number": "ORD-1"},
        )
        assert r.matched_identifier == "tracking_number"


# ---------------------------------------------------------------------------
# Degraded readiness
# ---------------------------------------------------------------------------

class TestDegraded:
    def test_degraded_identifier_present(self):
        r = check_readiness(
            _cap(full=["order_number"], degraded=["customer_name"]),
            {"customer_name": "Acme"},
        )
        assert r.quality == "degraded"
        assert r.can_execute is True
        assert r.matched_identifier == "customer_name"

    def test_first_degraded_identifier_wins(self):
        r = check_readiness(
            _cap(degraded=["customer_name", "customer_identifier"]),
            {"customer_name": "Acme", "customer_identifier": "C-1"},
        )
        assert r.matched_identifier == "customer_name"


# ---------------------------------------------------------------------------
# Insufficient readiness
# ---------------------------------------------------------------------------

class TestInsufficient:
    def test_no_identifier_present(self):
        r = check_readiness(
            _cap(full=["order_number"], degraded=["customer_name"]),
            {},
        )
        assert r.quality == "insufficient"
        assert r.can_execute is False
        assert set(r.missing_identifiers) == {"order_number", "customer_name"}

    def test_empty_string_not_counted(self):
        r = check_readiness(
            _cap(full=["customer_identifier"]),
            {"customer_identifier": "  "},
        )
        assert r.quality == "insufficient"
        assert r.can_execute is False

    def test_irrelevant_params_dont_help(self):
        r = check_readiness(
            _cap(full=["order_number"]),
            {"email": "a@b.com", "business_line": "bio"},
        )
        assert r.quality == "insufficient"

    def test_missing_identifiers_lists_all(self):
        r = check_readiness(
            _cap(full=["tracking_number"], degraded=["order_number", "customer_name"]),
            {},
        )
        assert r.missing_identifiers == ["tracking_number", "order_number", "customer_name"]


# ---------------------------------------------------------------------------
# Real tool scenarios
# ---------------------------------------------------------------------------

class TestRealToolScenarios:
    def test_order_lookup_with_order_number(self):
        cap = ToolCapability(
            tool_name="order_lookup_tool",
            full_identifiers=["order_number"],
            degraded_identifiers=["customer_name", "customer_identifier"],
        )
        r = check_readiness(cap, {"order_number": "ORD-123"})
        assert r.quality == "full"

    def test_order_lookup_with_customer_name(self):
        cap = ToolCapability(
            tool_name="order_lookup_tool",
            full_identifiers=["order_number"],
            degraded_identifiers=["customer_name", "customer_identifier"],
        )
        r = check_readiness(cap, {"customer_name": "Acme"})
        assert r.quality == "degraded"

    def test_order_lookup_with_nothing(self):
        cap = ToolCapability(
            tool_name="order_lookup_tool",
            full_identifiers=["order_number"],
            degraded_identifiers=["customer_name", "customer_identifier"],
        )
        r = check_readiness(cap, {"email": "abc@test.com"})
        assert r.quality == "insufficient"

    def test_shipping_with_tracking_number(self):
        cap = ToolCapability(
            tool_name="shipping_lookup_tool",
            full_identifiers=["tracking_number"],
            degraded_identifiers=["order_number", "customer_name"],
        )
        r = check_readiness(cap, {"tracking_number": "TRK-1"})
        assert r.quality == "full"

    def test_shipping_with_customer_name(self):
        """Shipping with only customer_name → degraded (was insufficient in old design)."""
        cap = ToolCapability(
            tool_name="shipping_lookup_tool",
            full_identifiers=["tracking_number"],
            degraded_identifiers=["order_number", "customer_name"],
        )
        r = check_readiness(cap, {"customer_name": "Acme"})
        assert r.quality == "degraded"

    def test_rag_always_full(self):
        cap = ToolCapability(tool_name="technical_rag_tool")
        r = check_readiness(cap, {})
        assert r.quality == "full"
        assert r.can_execute is True
