"""Tests for src/agent/state.py — AgentState and GroupOutcome."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.state import AgentState, GroupOutcome
from src.common.execution_models import ExecutedToolCall, ExecutionResult
from src.common.models import IntentGroup
from src.routing.models import ClarificationPayload, RouteDecision
from src.tools.models import ToolRequest, ToolResult


def _group(intent: str = "pricing_question", object_type: str = "product") -> IntentGroup:
    return IntentGroup(intent=intent, object_type=object_type, confidence=0.85)


def _route(action: str = "execute", clarification: ClarificationPayload | None = None) -> RouteDecision:
    return RouteDecision(action=action, clarification=clarification)


def _execution(status: str = "ok", tool_name: str = "catalog_lookup_tool") -> ExecutionResult:
    return ExecutionResult(
        executed_calls=[
            ExecutedToolCall(
                call_id="c1",
                tool_name=tool_name,
                status=status,
                request=ToolRequest(tool_name=tool_name, query="test"),
                result=ToolResult(tool_name=tool_name, status=status),
            )
        ],
        final_status=status,
        reason=f"tool {tool_name} returned {status}",
    )


def _empty_result(reason: str = "no execution") -> ExecutionResult:
    return ExecutionResult(final_status="empty", reason=reason)


# --- AgentState.record ---

def test_record_adds_outcome():
    state = AgentState()
    state.record(_group(), _route(), _execution())
    assert len(state.outcomes) == 1
    assert state.outcomes[0].status == "resolved"
    assert state.outcomes[0].action == "execute"


# --- overall_action ---

def test_overall_action_single_execute():
    state = AgentState()
    state.record(_group(), _route("execute"), _execution(), status="resolved")
    assert state.overall_action == "execute"


def test_overall_action_single_clarify():
    state = AgentState()
    state.record(_group(), _route("clarify"), _empty_result(), status="needs_clarification")
    assert state.overall_action == "clarify"


def test_overall_action_single_handoff():
    state = AgentState()
    state.record(_group(), _route("handoff"), _empty_result(), status="needs_handoff")
    assert state.overall_action == "handoff"


def test_overall_action_mixed_execute_and_clarify():
    """When some groups resolved and others need clarification, overall = execute."""
    state = AgentState()
    state.record(_group("pricing_question"), _route("execute"), _execution(), status="resolved")
    state.record(
        _group("order_support", "order"),
        _route("clarify", ClarificationPayload(prompt="Which order?")),
        _empty_result(),
        status="needs_clarification",
    )
    assert state.overall_action == "execute"


def test_overall_action_handoff_takes_priority():
    state = AgentState()
    state.record(_group("pricing_question"), _route("execute"), _execution(), status="resolved")
    state.record(_group("order_support"), _route("handoff"), _empty_result(), status="needs_handoff")
    assert state.overall_action == "handoff"


def test_overall_action_respond():
    state = AgentState()
    state.record(_group(), _route("respond"), _empty_result(), status="resolved")
    assert state.overall_action == "respond"


# --- merged_execution_result ---

def test_merged_execution_result_combines_calls():
    state = AgentState()
    state.record(_group("pricing"), _route(), _execution("ok", "pricing_lookup_tool"), status="resolved")
    state.record(_group("technical"), _route(), _execution("ok", "technical_rag_tool"), status="resolved")

    merged = state.merged_execution_result
    assert len(merged.executed_calls) == 2
    assert merged.final_status == "ok"
    tool_names = {c.tool_name for c in merged.executed_calls}
    assert tool_names == {"pricing_lookup_tool", "technical_rag_tool"}


def test_merged_execution_result_partial_when_mixed():
    state = AgentState()
    state.record(_group("a"), _route(), _execution("ok", "tool_a"), status="resolved")
    state.record(_group("b"), _route(), _execution("error", "tool_b"), status="resolved")

    merged = state.merged_execution_result
    assert merged.final_status == "partial"


def test_merged_execution_result_excludes_clarification_groups():
    state = AgentState()
    state.record(_group("a"), _route(), _execution("ok", "tool_a"), status="resolved")
    state.record(_group("b"), _route("clarify"), _empty_result(), status="needs_clarification")

    merged = state.merged_execution_result
    assert len(merged.executed_calls) == 1
    assert merged.executed_calls[0].tool_name == "tool_a"


def test_merged_execution_result_empty_when_no_resolved():
    state = AgentState()
    state.record(_group(), _route("clarify"), _empty_result(), status="needs_clarification")

    merged = state.merged_execution_result
    assert merged.final_status == "empty"
    assert len(merged.executed_calls) == 0


# --- primary_route_decision ---

def test_primary_route_decision_prefers_handoff():
    state = AgentState()
    state.record(_group("a"), _route("execute"), _execution(), status="resolved")
    state.record(_group("b"), _route("handoff"), _empty_result(), status="needs_handoff")

    assert state.primary_route_decision.action == "handoff"


def test_primary_route_decision_clarify_when_all_clarify():
    state = AgentState()
    state.record(_group(), _route("clarify"), _empty_result(), status="needs_clarification")

    assert state.primary_route_decision.action == "clarify"


def test_primary_route_decision_prefers_execute():
    state = AgentState()
    state.record(_group("a"), _route("respond"), _empty_result(), status="resolved")
    state.record(_group("b"), _route("execute"), _execution(), status="resolved")

    assert state.primary_route_decision.action == "execute"


# --- primary_clarification ---

def test_primary_clarification_returns_first_clarification():
    state = AgentState()
    clar = ClarificationPayload(prompt="Which order?", missing_information=["order_number"])
    state.record(_group("a"), _route("execute"), _execution(), status="resolved")
    state.record(_group("b"), _route("clarify", clar), _empty_result(), status="needs_clarification")

    assert state.primary_clarification is not None
    assert state.primary_clarification.prompt == "Which order?"


def test_primary_clarification_none_when_all_resolved():
    state = AgentState()
    state.record(_group(), _route("execute"), _execution(), status="resolved")

    assert state.primary_clarification is None


# --- debug_summary ---

def test_debug_summary_structure():
    state = AgentState()
    state.record(_group("pricing"), _route("execute"), _execution(), status="resolved")
    state.record(_group("order"), _route("clarify"), _empty_result(), status="needs_clarification")

    summary = state.debug_summary()
    assert summary["total_groups"] == 2
    assert summary["resolved"] == 1
    assert summary["needs_clarification"] == 1
    assert summary["overall_action"] == "execute"
    assert len(summary["groups"]) == 2


# --- edge cases ---

def test_empty_agent_state():
    state = AgentState()
    assert state.overall_action == "respond"
    assert state.merged_execution_result.final_status == "empty"
    assert state.primary_clarification is None
    assert state.debug_summary()["total_groups"] == 0
