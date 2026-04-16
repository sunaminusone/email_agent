from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.responser.composer as composer_module

from src.agent.state import AgentState, GroupOutcome
from src.common.execution_models import ExecutedToolCall, ExecutionResult
from src.common.models import DemandProfile, IntentGroup
from src.ingestion.models import ParserConstraints
from src.objects.models import ObjectCandidate, ResolvedObjectState
from src.routing.models import ClarificationPayload, DialogueActResult, RouteDecision
from src.tools.models import ToolRequest, ToolResult
from src.responser import ResponseInput, build_response_bundle, compose_response


def _empty_execution_result(
    *,
    executed_calls: list[ExecutedToolCall] | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        executed_calls=executed_calls or [],
    )


def test_compose_response_returns_direct_answer_for_grounded_lookup() -> None:
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody", "catalog_no": "A100"}],
            structured_facts={"species": ["human"], "application": ["flow cytometry"]},
        ),
    )
    response, plan = compose_response(
        ResponseInput(
            query="CD3",
            locale="en",
            execution_result=_empty_execution_result(executed_calls=[executed_call]),
        )
    )

    assert plan.response_mode == "direct_answer"
    assert response.response_type == "answer"
    assert "CD3" in response.message


def test_compose_response_returns_clarification_prompt() -> None:
    response, plan = compose_response(
        ResponseInput(
            query="that one",
            execution_result=_empty_execution_result(),
            action="clarify",
            clarification=ClarificationPayload(
                prompt="Which product did you mean?",
                missing_information=["product identifier"],
            ),
        )
    )

    assert plan.response_mode == "clarification"
    assert response.response_type == "clarification"
    assert response.message == "Which product did you mean?"


def test_compose_response_returns_termination_message() -> None:
    response, plan = compose_response(
        ResponseInput(
            query="stop",
            locale="en",
            dialogue_act=DialogueActResult(
                act="closing",
                matched_signals=["terminate_pattern"],
            ),
            execution_result=_empty_execution_result(),
        )
    )

    assert plan.response_mode == "termination"
    assert response.response_type == "termination"
    assert response.message == "Understood. I will stop here on this topic."


def test_build_response_bundle_derives_resolution_and_path() -> None:
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="technical_rag_tool",
        status="ok",
        request=ToolRequest(tool_name="technical_rag_tool", query="validation"),
        result=ToolResult(
            tool_name="technical_rag_tool",
            status="ok",
            unstructured_snippets=[{"content_preview": "Validated in flow cytometry."}],
        ),
    )

    bundle = build_response_bundle(
        ResponseInput(
            query="validation",
            execution_result=_empty_execution_result(executed_calls=[executed_call]),
        )
    )

    assert bundle.response_plan.answer_focus == "knowledge_lookup"
    assert bundle.response_topic == "knowledge_lookup"
    assert bundle.response_path in {"deterministic", "llm_rewrite"}


def test_compose_response_falls_back_when_rewrite_fails(monkeypatch) -> None:
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
            structured_facts={"species": ["human"]},
        ),
    )

    def _raise_rewrite(*args, **kwargs):
        raise RuntimeError("rewrite unavailable")

    monkeypatch.setattr(composer_module, "_rewrite_message", _raise_rewrite)

    bundle = build_response_bundle(
        ResponseInput(
            query="CD3",
            execution_result=_empty_execution_result(executed_calls=[executed_call]),
        )
    )

    assert bundle.response_path == "deterministic"
    assert bundle.composed_response.debug_info["rewrite_applied"] is False


def test_response_plan_updates_last_tool_results_memory() -> None:
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
        ),
    )

    bundle = build_response_bundle(
        ResponseInput(
            query="CD3",
            execution_result=_empty_execution_result(executed_calls=[executed_call]),
        )
    )

    assert bundle.response_plan.memory_update is not None
    assert bundle.response_plan.memory_update.response_memory is not None
    assert bundle.response_plan.memory_update.response_memory.last_tool_results == [
        {
            "tool_name": "catalog_lookup_tool",
            "status": "ok",
            "call_id": "1",
        }
    ]


# ---------------------------------------------------------------------------
# Locale tests
# ---------------------------------------------------------------------------

def test_compose_response_acknowledgement_zh() -> None:
    response, plan = compose_response(
        ResponseInput(
            query="好的",
            locale="zh",
            dialogue_act=DialogueActResult(act="closing"),
            execution_result=_empty_execution_result(),
        )
    )
    assert plan.response_mode == "acknowledgement"
    assert "收到" in response.message


def test_compose_response_acknowledgement_en() -> None:
    response, plan = compose_response(
        ResponseInput(
            query="ok thanks",
            locale="en",
            dialogue_act=DialogueActResult(act="closing"),
            execution_result=_empty_execution_result(),
        )
    )
    assert plan.response_mode == "acknowledgement"
    assert "Understood" in response.message


def test_compose_response_handoff_en() -> None:
    response, plan = compose_response(
        ResponseInput(
            query="I need to speak to a manager",
            locale="en",
            execution_result=_empty_execution_result(),
            action="handoff",
        )
    )
    assert plan.response_mode == "handoff"
    assert response.response_type == "handoff"
    assert "human review" in response.message.lower()


# ---------------------------------------------------------------------------
# Multi-group / partial_answer tests
# ---------------------------------------------------------------------------

def _make_group_outcome(
    intent: str,
    action: str,
    status: str,
    tool_name: str = "catalog_lookup_tool",
    clarification: ClarificationPayload | None = None,
):
    if action == "execute" and status == "resolved":
        execution_result = ExecutionResult(
            executed_calls=[
                ExecutedToolCall(
                    call_id="c1",
                    tool_name=tool_name,
                    status="ok",
                    request=ToolRequest(tool_name=tool_name, query="test"),
                    result=ToolResult(
                        tool_name=tool_name,
                        status="ok",
                        primary_records=[{"display_name": f"{intent} result"}],
                        structured_facts={"source": intent},
                    ),
                )
            ],
            final_status="ok",
        )
    else:
        execution_result = ExecutionResult(final_status="empty")

    return GroupOutcome(
        group=IntentGroup(intent=intent, confidence=0.85),
        action=action,
        route_decision=RouteDecision(action=action, clarification=clarification),
        execution_result=execution_result,
        status=status,
    )


def test_partial_answer_when_mixed_outcomes() -> None:
    """Some groups resolved + some need clarification → partial_answer mode."""
    resolved = _make_group_outcome("pricing_question", "execute", "resolved")
    needs_clar = _make_group_outcome(
        "order_support", "clarify", "needs_clarification",
        clarification=ClarificationPayload(prompt="Which order?", missing_information=["order_number"]),
    )

    merged_result = ExecutionResult(
        executed_calls=list(resolved.execution_result.executed_calls),
        final_status="ok",
    )

    bundle = build_response_bundle(ResponseInput(
        query="check price and order status",
        locale="en",
        execution_result=merged_result,
        action="execute",
        group_outcomes=[resolved, needs_clar],
    ))

    assert bundle.response_plan.response_mode == "partial_answer"
    assert bundle.composed_response.response_type == "partial_answer"
    assert "Which order?" in bundle.composed_response.message


def test_all_clarification_outcomes() -> None:
    """All groups need clarification → clarification mode."""
    needs_clar = _make_group_outcome(
        "order_support", "clarify", "needs_clarification",
        clarification=ClarificationPayload(prompt="Which order?"),
    )

    bundle = build_response_bundle(ResponseInput(
        query="check my order",
        locale="en",
        execution_result=ExecutionResult(),
        action="clarify",
        clarification=ClarificationPayload(prompt="Which order?"),
        group_outcomes=[needs_clar],
    ))

    assert bundle.response_plan.response_mode == "clarification"


def test_all_resolved_outcomes_no_partial() -> None:
    """All groups resolved → normal answer mode, not partial_answer."""
    resolved1 = _make_group_outcome("pricing_question", "execute", "resolved", "pricing_lookup_tool")
    resolved2 = _make_group_outcome("technical_question", "execute", "resolved", "technical_rag_tool")

    merged_calls = [
        *resolved1.execution_result.executed_calls,
        *resolved2.execution_result.executed_calls,
    ]
    merged_result = ExecutionResult(executed_calls=merged_calls, final_status="ok")

    bundle = build_response_bundle(ResponseInput(
        query="price and protocol for CAR-T",
        locale="en",
        execution_result=merged_result,
        action="execute",
        group_outcomes=[resolved1, resolved2],
    ))

    assert bundle.response_plan.response_mode == "direct_answer"


# ---------------------------------------------------------------------------
# Technical snippets rendering
# ---------------------------------------------------------------------------

def test_technical_snippets_cleaned_in_answer() -> None:
    """RAG snippet metadata prefixes should be stripped from the answer."""
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="technical_rag_tool",
        status="ok",
        request=ToolRequest(tool_name="technical_rag_tool", query="CAR-T workflow"),
        result=ToolResult(
            tool_name="technical_rag_tool",
            status="ok",
            unstructured_snippets=[{
                "content": "company: ProMab | tags: CAR-T, workflow | title: CAR-T workflow overview | body: The CAR-T development process involves antibody selection, construct generation, and cell production.",
                "title": "CAR-T workflow overview",
                "section_type": "workflow_overview",
            }],
        ),
    )

    response, plan = compose_response(
        ResponseInput(
            query="CAR-T workflow",
            locale="en",
            execution_result=_empty_execution_result(executed_calls=[executed_call]),
        )
    )

    assert "company: ProMab" not in response.message
    assert "tags:" not in response.message
    assert "CAR-T development process" in response.message or "antibody selection" in response.message


# ---------------------------------------------------------------------------
# Demand-aware planner tests
# ---------------------------------------------------------------------------

def test_mixed_demand_still_returns_direct_answer() -> None:
    """Mixed demand (technical + commercial) → direct_answer, no separate hybrid mode."""
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
        ),
    )

    bundle = build_response_bundle(ResponseInput(
        query="CD3 price and protocol",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
        demand_profile=DemandProfile(
            primary_demand="technical",
            secondary_demands=["commercial"],
            active_request_flags=["needs_protocol", "needs_price"],
        ),
    ))

    assert bundle.response_plan.response_mode == "direct_answer"


def test_planner_selects_direct_when_demand_single_focus() -> None:
    """Pure technical demand → direct_answer even with multiple blocks."""
    calls = [
        ExecutedToolCall(
            call_id="1",
            tool_name="catalog_lookup_tool",
            status="ok",
            request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
            result=ToolResult(
                tool_name="catalog_lookup_tool", status="ok",
                primary_records=[{"display_name": "CD3 Antibody"}],
                structured_facts={"species": ["human"]},
            ),
        ),
        ExecutedToolCall(
            call_id="2",
            tool_name="technical_rag_tool",
            status="ok",
            request=ToolRequest(tool_name="technical_rag_tool", query="CD3"),
            result=ToolResult(
                tool_name="technical_rag_tool", status="ok",
                unstructured_snippets=[{"content": "Protocol info"}],
            ),
        ),
    ]

    bundle = build_response_bundle(ResponseInput(
        query="CD3 protocol details",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=calls),
        demand_profile=DemandProfile(
            primary_demand="technical",
            active_request_flags=["needs_protocol"],
        ),
    ))

    assert bundle.response_plan.response_mode == "direct_answer"


def test_memory_update_stores_primary_demand_only() -> None:
    """Memory should store primary demand's flags, not all flags from mixed query."""
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool", status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
        ),
    )

    bundle = build_response_bundle(ResponseInput(
        query="CD3 price and protocol",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
        demand_profile=DemandProfile(
            primary_demand="technical",
            secondary_demands=["commercial"],
            active_request_flags=["needs_protocol", "needs_price"],
        ),
    ))

    mem = bundle.response_plan.memory_update.response_memory
    assert mem.last_demand_type == "technical"
    # Only technical flags stored — needs_price (commercial) excluded
    assert "needs_protocol" in mem.last_demand_flags
    assert "needs_price" not in mem.last_demand_flags


# ---------------------------------------------------------------------------
# Topic continuity tests
# ---------------------------------------------------------------------------

def _make_response_memory_with_topics(topics: list[str]):
    from src.memory.models import ResponseMemory
    return ResponseMemory(last_response_topics=topics)


def test_topic_continuing_suppresses_object_acknowledgement() -> None:
    """When last topic matches current focus, should_acknowledge_object is False."""
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
            structured_facts={"species": ["human"]},
        ),
    )

    # First turn: no prior topics → should_acknowledge_object may be True
    bundle_first = build_response_bundle(ResponseInput(
        query="CD3",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
    ))

    # Second turn: prior topic matches → should_acknowledge_object is False
    bundle_second = build_response_bundle(ResponseInput(
        query="CD3 applications",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
        response_memory=_make_response_memory_with_topics([
            bundle_first.response_plan.answer_focus,
        ]),
    ))

    assert bundle_second.response_plan.should_acknowledge_object is False


def test_topic_continuing_demotes_object_summary_block() -> None:
    """On consecutive same-topic, object_summary should not be in primary blocks."""
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
            structured_facts={"species": ["human"]},
        ),
    )

    bundle = build_response_bundle(ResponseInput(
        query="CD3 details",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
        response_memory=_make_response_memory_with_topics(["commercial_or_operational_lookup"]),
    ))

    primary_types = [b.block_type for b in bundle.response_plan.primary_content_blocks]
    assert "object_summary" not in primary_types


def test_topic_continuing_enables_llm_rewrite() -> None:
    """Consecutive same-topic turns should prefer LLM rewrite."""
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
        ),
    )

    # Without prior topics — only primary_records, no informational blocks → no rewrite
    bundle_cold = build_response_bundle(ResponseInput(
        query="CD3",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
    ))

    # With matching prior topic → rewrite enabled even with same blocks
    bundle_warm = build_response_bundle(ResponseInput(
        query="CD3",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
        response_memory=_make_response_memory_with_topics([
            bundle_cold.response_plan.answer_focus,
        ]),
    ))

    assert bundle_warm.response_plan.should_use_llm_rewrite is True


def test_no_topic_continuity_for_control_topics() -> None:
    """Control topics (closing, clarification) should not trigger continuity."""
    response, plan = compose_response(
        ResponseInput(
            query="ok thanks",
            locale="en",
            dialogue_act=DialogueActResult(act="closing"),
            execution_result=_empty_execution_result(),
            response_memory=_make_response_memory_with_topics(["conversation_control"]),
        )
    )

    # acknowledgement is a control topic — should not activate continuity rules
    assert plan.response_mode == "acknowledgement"


# ---------------------------------------------------------------------------
# Parser constraints in content blocks
# ---------------------------------------------------------------------------

def test_object_summary_block_includes_customer_constraints() -> None:
    """When parser_constraints has non-None values, they appear in block data."""
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
            structured_facts={"species": ["human"]},
        ),
    )
    primary = ObjectCandidate(
        object_type="product",
        canonical_value="CD3",
        display_name="CD3 Antibody",
        identifier="A100",
    )
    constraints = ParserConstraints(budget="5000 USD", format_or_size="50 kDa")

    bundle = build_response_bundle(ResponseInput(
        query="CD3",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
        resolved_object_state=ResolvedObjectState(primary_object=primary),
        dialogue_act=DialogueActResult(act="inquiry"),
        parser_constraints=constraints,
    ))

    # Find the object_summary block
    obj_blocks = [
        b for b in bundle.composed_response.content_blocks
        if b.block_type == "object_summary"
    ]
    assert len(obj_blocks) == 1
    data = obj_blocks[0].data
    assert "customer_constraints" in data
    assert data["customer_constraints"]["budget"] == "5000 USD"
    assert data["customer_constraints"]["format_or_size"] == "50 kDa"
    # None fields should not appear
    assert "timeline_requirement" not in data["customer_constraints"]


def test_no_customer_constraints_when_none() -> None:
    """Without parser_constraints, no customer_constraints key in block data."""
    executed_call = ExecutedToolCall(
        call_id="1",
        tool_name="catalog_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="catalog_lookup_tool", query="CD3"),
        result=ToolResult(
            tool_name="catalog_lookup_tool",
            status="ok",
            primary_records=[{"display_name": "CD3 Antibody"}],
        ),
    )
    primary = ObjectCandidate(
        object_type="product",
        canonical_value="CD3",
        display_name="CD3 Antibody",
        identifier="A100",
    )

    bundle = build_response_bundle(ResponseInput(
        query="CD3",
        locale="en",
        execution_result=_empty_execution_result(executed_calls=[executed_call]),
        resolved_object_state=ResolvedObjectState(primary_object=primary),
        dialogue_act=DialogueActResult(act="inquiry"),
    ))

    obj_blocks = [
        b for b in bundle.composed_response.content_blocks
        if b.block_type == "object_summary"
    ]
    if obj_blocks:
        assert "customer_constraints" not in obj_blocks[0].data
