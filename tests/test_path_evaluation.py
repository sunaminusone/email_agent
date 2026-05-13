"""Tests for src.executor.path_evaluation."""
from __future__ import annotations

import pytest

from src.executor.models import ToolSelection
from src.executor.path_evaluation import evaluate_execution_paths
from src.tools.models import ToolCapability
from src.tools.registry import clear_registry, register_tool


class _DummyExecutor:
    def execute(self, request):
        return None


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure a clean tool registry for each test."""
    clear_registry()
    yield
    clear_registry()


def _register(
    name: str,
    full: list[str] | None = None,
    degraded: list[str] | None = None,
    provides: list[str] | None = None,
) -> None:
    register_tool(
        tool_name=name,
        executor=_DummyExecutor(),
        capability=ToolCapability(
            tool_name=name,
            full_identifiers=full or [],
            degraded_identifiers=degraded or [],
            provides_params=provides or [],
        ),
    )


def _sel(name: str, score: float = 0.5, role: str = "primary") -> ToolSelection:
    return ToolSelection(tool_name=name, match_score=score, role=role)


# ---------------------------------------------------------------------------
# Execute when at least one path is ready
# ---------------------------------------------------------------------------

class TestExecutePaths:
    def test_no_identifiers_always_executable(self):
        """Tools with no identifiers (RAG, catalog) are always full."""
        _register("catalog_lookup_tool")
        sels = [_sel("catalog_lookup_tool", 0.8)]
        result = evaluate_execution_paths(sels, "product", {})
        assert result.recommended_action == "execute"
        assert len(result.executable_paths) == 1
        assert result.executable_paths[0].readiness.quality == "full"

    def test_full_preferred_over_degraded(self):
        """Full identifier tool beats higher-scored degraded tool."""
        _register("tool_a", full=["order_number"])
        _register("tool_b", full=["order_number"], degraded=["customer_name"])
        sels = [_sel("tool_a", 0.5), _sel("tool_b", 0.7)]
        available = {"customer_name": "Acme"}

        result = evaluate_execution_paths(sels, "order", available)
        assert result.recommended_action == "execute"
        # tool_b is degraded (0.7 * 0.6 = 0.42), tool_a is insufficient
        # Only tool_b is executable
        assert result.executable_paths[0].tool_name == "tool_b"

    def test_degraded_still_executable(self):
        _register("tool_a", full=["order_number"], degraded=["customer_name"])
        result = evaluate_execution_paths(
            [_sel("tool_a")], "order", {"customer_name": "Acme"},
        )
        assert result.recommended_action == "execute"
        assert result.executable_paths[0].readiness.quality == "degraded"


# ---------------------------------------------------------------------------
# Clarify when all paths blocked
# ---------------------------------------------------------------------------

class TestClarifyPaths:
    def test_all_insufficient_triggers_clarify(self):
        _register("order_tool", full=["order_number"], degraded=["customer_name"])
        result = evaluate_execution_paths(
            [_sel("order_tool")], "order", {},
        )
        assert result.recommended_action == "clarify"
        assert len(result.blocked_paths) == 1
        assert result.clarification_context is not None
        assert "order_tool" in result.clarification_context.missing_by_path

    def test_clarification_context_lists_missing_identifiers(self):
        _register("tool_x", full=["invoice_number"], degraded=["customer_name"])
        result = evaluate_execution_paths([_sel("tool_x")], "invoice", {})
        missing = result.clarification_context.missing_by_path["tool_x"]
        assert set(missing) == {"invoice_number", "customer_name"}


# ---------------------------------------------------------------------------
# Mixed paths: some executable, some blocked
# ---------------------------------------------------------------------------

class TestMixedPaths:
    def test_executable_path_overrides_blocked(self):
        _register("rag_tool")  # no identifiers → always full
        _register("order_tool", full=["order_number"])
        sels = [_sel("rag_tool", 0.6), _sel("order_tool", 0.8)]
        result = evaluate_execution_paths(sels, "order", {})
        assert result.recommended_action == "execute"
        assert len(result.executable_paths) == 1
        assert result.executable_paths[0].tool_name == "rag_tool"
        assert len(result.blocked_paths) == 1


# ---------------------------------------------------------------------------
# Effective priority calculation
# ---------------------------------------------------------------------------

class TestEffectivePriority:
    def test_full_weight_1(self):
        _register("t")
        result = evaluate_execution_paths([_sel("t", 0.9)], "x", {})
        assert result.executable_paths[0].effective_priority == 0.9

    def test_degraded_weight_06(self):
        _register("t", full=["order_number"], degraded=["customer_name"])
        result = evaluate_execution_paths(
            [_sel("t", 1.0)], "order", {"customer_name": "Acme"},
        )
        path = result.executable_paths[0]
        assert path.readiness.quality == "degraded"
        assert path.effective_priority == pytest.approx(0.6, abs=0.01)
