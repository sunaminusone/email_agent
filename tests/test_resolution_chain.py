"""Tests for resolution chain logic in src.executor.path_evaluation."""
from __future__ import annotations

import pytest

from src.executor.models import ToolSelection
from src.executor.path_evaluation import (
    evaluate_execution_paths,
    find_resolution_provider,
)
from src.tools.models import ToolCapability
from src.tools.registry import clear_registry, register_tool


class _DummyExecutor:
    def execute(self, request):
        return None


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    _register_standard_tools()
    yield
    clear_registry()


def _register_standard_tools():
    """Register the standard QuickBooks tools with their new simplified declarations."""
    register_tool(
        tool_name="customer_lookup_tool",
        executor=_DummyExecutor(),
        capability=ToolCapability(
            tool_name="customer_lookup_tool",
            full_identifiers=["customer_identifier"],
            provides_params=["customer_name", "customer_identifier", "email"],
        ),
    )
    register_tool(
        tool_name="order_lookup_tool",
        executor=_DummyExecutor(),
        capability=ToolCapability(
            tool_name="order_lookup_tool",
            full_identifiers=["order_number"],
            degraded_identifiers=["customer_name", "customer_identifier"],
            provides_params=["order_number", "customer_name", "invoice_number"],
        ),
    )
    register_tool(
        tool_name="shipping_lookup_tool",
        executor=_DummyExecutor(),
        capability=ToolCapability(
            tool_name="shipping_lookup_tool",
            full_identifiers=["tracking_number"],
            degraded_identifiers=["order_number", "customer_name"],
            provides_params=["tracking_number", "order_number", "customer_name"],
        ),
    )
    register_tool(
        tool_name="invoice_lookup_tool",
        executor=_DummyExecutor(),
        capability=ToolCapability(
            tool_name="invoice_lookup_tool",
            full_identifiers=["invoice_number"],
            degraded_identifiers=["order_number", "customer_name"],
            provides_params=["invoice_number", "order_number", "customer_name"],
        ),
    )
    register_tool(
        tool_name="catalog_lookup_tool",
        executor=_DummyExecutor(),
        capability=ToolCapability(
            tool_name="catalog_lookup_tool",
            provides_params=["catalog_number", "product_name", "business_line"],
        ),
    )


def _sel(name: str, score: float = 0.5) -> ToolSelection:
    return ToolSelection(tool_name=name, match_score=score)


# ---------------------------------------------------------------------------
# "Where is my order?" + email scenario
# ---------------------------------------------------------------------------

class TestOrderWithEmail:
    """The canonical resolution chain scenario from the design doc."""

    def test_order_lookup_insufficient_without_params(self):
        path_eval = evaluate_execution_paths(
            [_sel("order_lookup_tool")], "order", {},
        )
        assert path_eval.recommended_action == "clarify"

    def test_customer_lookup_resolves_with_identifier(self):
        """With customer_identifier available, customer_lookup can provide customer_name."""
        # order_lookup has customer_identifier as degraded → it's already executable!
        path_eval = evaluate_execution_paths(
            [_sel("order_lookup_tool")], "order", {"customer_identifier": "abc@example.com"},
        )
        assert path_eval.recommended_action == "execute"

    def test_resolution_chain_with_customer_identifier(self):
        """When shipping_lookup is blocked, customer_lookup can provide customer_name."""
        path_eval = evaluate_execution_paths(
            [_sel("shipping_lookup_tool")], "shipment", {},
        )
        assert path_eval.recommended_action == "clarify"

        # With customer_identifier → customer_lookup can run (full) → provides customer_name
        provider = find_resolution_provider(
            path_eval, {"customer_identifier": "abc@example.com"},
        )
        assert provider == "customer_lookup_tool"

    def test_email_does_not_directly_resolve(self):
        """email != customer_identifier, so no direct resolution."""
        path_eval = evaluate_execution_paths(
            [_sel("order_lookup_tool")], "order", {"email": "abc@example.com"},
        )
        assert path_eval.recommended_action == "clarify"

        provider = find_resolution_provider(
            path_eval, {"email": "abc@example.com"},
        )
        # customer_lookup needs customer_identifier, email != customer_identifier
        assert provider is None


# ---------------------------------------------------------------------------
# No resolution possible
# ---------------------------------------------------------------------------

class TestNoResolution:
    def test_no_params_no_provider(self):
        path_eval = evaluate_execution_paths(
            [_sel("order_lookup_tool")], "order", {},
        )
        provider = find_resolution_provider(path_eval, {})
        assert provider is None

    def test_no_blocked_paths_no_provider(self):
        path_eval = evaluate_execution_paths(
            [_sel("catalog_lookup_tool")], "product", {},
        )
        assert path_eval.recommended_action == "execute"
        provider = find_resolution_provider(path_eval, {})
        assert provider is None


# ---------------------------------------------------------------------------
# Invoice resolution via order
# ---------------------------------------------------------------------------

class TestInvoiceResolution:
    def test_invoice_blocked_order_can_help(self):
        """Invoice lookup needs invoice_number/order_number/customer_name.
        If order_number is available, order_lookup can run (full) and provide customer_name."""
        path_eval = evaluate_execution_paths(
            [_sel("invoice_lookup_tool")], "invoice", {},
        )
        assert path_eval.recommended_action == "clarify"

        # With order_number available, order_lookup can run (full) → provides customer_name
        provider = find_resolution_provider(
            path_eval, {"order_number": "ORD-123"},
        )
        assert provider == "order_lookup_tool"


# ---------------------------------------------------------------------------
# Provider must be full (not degraded)
# ---------------------------------------------------------------------------

class TestProviderMustBeFull:
    def test_degraded_provider_rejected(self):
        """A provider that would only be degraded is NOT used."""
        # shipping_lookup is blocked (needs tracking/order/customer)
        path_eval = evaluate_execution_paths(
            [_sel("shipping_lookup_tool")], "shipment", {},
        )
        assert path_eval.recommended_action == "clarify"

        # order_lookup with customer_name → degraded → should NOT be used as provider
        provider = find_resolution_provider(
            path_eval, {"customer_name": "Acme"},
        )
        # order_lookup is degraded with customer_name, not full
        # But shipping_lookup itself has customer_name as degraded_identifier
        # So shipping_lookup would actually be executable (degraded) with customer_name!
        # Let me re-check: the path_eval was computed with {} params.
        # find_resolution_provider checks if a provider can give missing identifiers.
        # shipping needs: tracking_number, order_number, customer_name
        # customer_name is available → but we computed path_eval with {} so shipping is blocked.
        # However the provider search uses available_params={"customer_name": "Acme"}
        # order_lookup with customer_name → degraded, not full → rejected
        # customer_lookup needs customer_identifier → not in {"customer_name"} → insufficient
        # No full provider → None
        assert provider is None
