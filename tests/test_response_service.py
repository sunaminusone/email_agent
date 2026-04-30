from pathlib import Path
import sys
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.state import GroupOutcome
from src.common.execution_models import ExecutedToolCall, ExecutionResult
from src.common.models import DemandProfile, IntentGroup
from src.ingestion.models import ParserConstraints
from src.objects.models import ObjectCandidate, ResolvedObjectState
from src.routing.models import ClarificationPayload, DialogueActResult, RouteDecision
from src.tools.models import ToolRequest, ToolResult
from src.responser import ResponseInput, build_response_bundle, compose_response
from src.responser.csr.composer import render_csr_draft_response
from src.responser.models import ResponsePlan, build_response_memory_contribution


def _empty_execution_result(
    *,
    executed_calls: list[ExecutedToolCall] | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        executed_calls=executed_calls or [],
    )


class _FakeStructuredLLM:
    def __init__(self, draft: str) -> None:
        self._draft = draft

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        class _Result:
            draft = ""

        result = _Result()
        result.draft = self._draft
        return result


# ---------------------------------------------------------------------------
# answer_focus + csr_draft renderer wiring
# ---------------------------------------------------------------------------


def test_grounded_lookup_yields_commercial_focus_in_csr_draft() -> None:
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

    assert plan.answer_focus == "commercial_or_operational_lookup"
    assert response.response_type == "csr_draft"


def test_termination_signal_sets_conversation_close_focus() -> None:
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

    assert plan.answer_focus == "conversation_close"
    assert response.response_type == "csr_draft"
    # Termination must trigger soft_reset so the next turn starts fresh.
    assert plan.memory_update.soft_reset_current_topic is True


def test_closing_without_terminate_signal_yields_conversation_control() -> None:
    response, plan = compose_response(
        ResponseInput(
            query="ok thanks",
            locale="en",
            dialogue_act=DialogueActResult(act="closing"),
            execution_result=_empty_execution_result(),
        )
    )

    assert plan.answer_focus == "conversation_control"
    assert response.response_type == "csr_draft"
    assert plan.memory_update.soft_reset_current_topic is False


def test_response_memory_contribution_preserves_soft_reset_control_signal() -> None:
    _, plan = compose_response(
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

    contribution = build_response_memory_contribution(plan)

    assert contribution.soft_reset_current_topic is True


def test_clarify_action_yields_missing_information_focus() -> None:
    _, plan = compose_response(
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

    assert plan.answer_focus == "missing_information"


def test_handoff_action_yields_human_review_focus() -> None:
    _, plan = compose_response(
        ResponseInput(
            query="I need to speak to a manager",
            locale="en",
            execution_result=_empty_execution_result(),
            action="handoff",
        )
    )

    assert plan.answer_focus == "human_review"


# ---------------------------------------------------------------------------
# response_topic + response_path derivation
# ---------------------------------------------------------------------------


def test_build_response_bundle_derives_topic_and_path() -> None:
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
    assert bundle.response_path == "csr_renderer_direct"


# ---------------------------------------------------------------------------
# Memory update wiring
# ---------------------------------------------------------------------------


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
# Group-outcome → answer_focus shortcuts
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


def test_group_outcomes_with_clarification_yield_missing_info_focus() -> None:
    """Any group needing clarification → answer_focus collapses to missing_information."""
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

    assert bundle.response_plan.answer_focus == "missing_information"


def test_all_resolved_outcomes_yield_informational_focus() -> None:
    """All groups resolved + tool results → falls through to informational focus inference."""
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

    assert bundle.response_plan.answer_focus in {
        "knowledge_lookup",
        "commercial_or_operational_lookup",
        "general_support",
    }


# ---------------------------------------------------------------------------
# Topic continuity behaviour
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


def test_no_topic_continuity_for_control_topics() -> None:
    """Control-topic acknowledgement should not activate continuity rules."""
    _, plan = compose_response(
        ResponseInput(
            query="ok thanks",
            locale="en",
            dialogue_act=DialogueActResult(act="closing"),
            execution_result=_empty_execution_result(),
            response_memory=_make_response_memory_with_topics(["conversation_control"]),
        )
    )

    assert plan.answer_focus == "conversation_control"


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

    # csr_draft now returns multiple structured blocks, but the planner's
    # object_summary block still lives on the ResponsePlan instead.
    plan_blocks = [
        *bundle.response_plan.primary_content_blocks,
        *bundle.response_plan.supporting_content_blocks,
    ]
    obj_blocks = [b for b in plan_blocks if b.block_type == "object_summary"]
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

    plan_blocks = [
        *bundle.response_plan.primary_content_blocks,
        *bundle.response_plan.supporting_content_blocks,
    ]
    obj_blocks = [b for b in plan_blocks if b.block_type == "object_summary"]
    if obj_blocks:
        assert "customer_constraints" not in obj_blocks[0].data


def test_csr_draft_marks_ungrounded_when_no_references_exist() -> None:
    with patch("src.responser.csr.draft_llm.get_llm", return_value=_FakeStructuredLLM("Please share more project details.")):
        response = render_csr_draft_response(
            ResponseInput(
                query="We need a monoclonal antibody against a membrane protein. What do you need for a quote?",
                execution_result=_empty_execution_result(),
            ),
            ResponsePlan(answer_focus="commercial_or_operational_lookup"),
        )

    assert response.response_type == "csr_draft"
    assert response.debug_info["grounding_status"] == "ungrounded"
    trust_block = next(block for block in response.content_blocks if block.block_type == "trust_signal")
    assert trust_block.data["grounding_status"] == "ungrounded"
    assert "No live data, strong historical replies, or relevant documents were retrieved" in trust_block.body
    assert "*📚 Similar past inquiries*" in response.message
    assert "No strong similar historical replies were retrieved" in response.message
    assert "*📄 Relevant documents*" in response.message


def test_csr_draft_surfaces_structured_reference_blocks_when_grounded() -> None:
    historical_call = ExecutedToolCall(
        call_id="hist-1",
        tool_name="historical_thread_tool",
        status="ok",
        request=ToolRequest(tool_name="historical_thread_tool", query="stable cell line"),
        result=ToolResult(
            tool_name="historical_thread_tool",
            status="ok",
            structured_facts={
                "threads": [
                    {
                        "submission_id": "s1",
                        "best_score": 0.91,
                        "reply_count": 1,
                        "units": [
                            {
                                "submitted_at": "2026-01-01T00:00:00",
                                "sender_name": "Sarah",
                                "institution": "Emory",
                                "service_of_interest": "Stable Cell Line Development",
                                "products_of_interest": "",
                                "page_content": "Customer message: quote for stable line\nSales reply: please share host cell and target details",
                            }
                        ],
                    }
                ],
            },
        ),
    )
    rag_call = ExecutedToolCall(
        call_id="rag-1",
        tool_name="technical_rag_tool",
        status="ok",
        request=ToolRequest(tool_name="technical_rag_tool", query="stable cell line"),
        result=ToolResult(
            tool_name="technical_rag_tool",
            status="ok",
            structured_facts={
                "matches": [
                    {
                        "section_type": "service_overview",
                        "chunk_label": "Stable Cell Line Flyer",
                        "final_score": 1.72,
                        "content_preview": "Stable cell line development service details.",
                    }
                ],
                "retrieval_confidence": {"level": "high"},
            },
        ),
    )

    with patch("src.responser.csr.draft_llm.get_llm", return_value=_FakeStructuredLLM("We can help with stable cell line development. Please share the target and host system.")):
        response = render_csr_draft_response(
            ResponseInput(
                query="We need a stable cell line quote.",
                execution_result=_empty_execution_result(executed_calls=[historical_call, rag_call]),
            ),
            ResponsePlan(answer_focus="commercial_or_operational_lookup"),
        )

    block_types = [block.block_type for block in response.content_blocks]
    assert response.debug_info["grounding_status"] == "grounded"
    assert "trust_signal" in block_types
    assert "historical_references" in block_types
    assert "relevant_documents" in block_types
    draft_block = next(block for block in response.content_blocks if block.block_type == "csr_draft")
    assert draft_block.data["grounding_status"] == "grounded"
    assert "*🧭 Grounding signal*" in response.message
    assert "*📚 Similar past inquiries*" in response.message
    assert "*📄 Relevant documents*" in response.message


def test_csr_draft_surfaces_live_pricing_records_from_pricing_lookup_tool() -> None:
    """Live pricing facts must reach the CSR draft (regression: silent drop)."""
    pricing_call = ExecutedToolCall(
        call_id="price-1",
        tool_name="pricing_lookup_tool",
        status="ok",
        request=ToolRequest(tool_name="pricing_lookup_tool", query="CD45 antibody"),
        result=ToolResult(
            tool_name="pricing_lookup_tool",
            status="ok",
            primary_records=[
                {
                    "catalog_no": "20081",
                    "name": "Anti-CD45 mAb",
                    "price": 350.0,
                    "currency": "USD",
                    "lead_time": "in stock",
                    "size": "100 ug",
                    "business_line": "antibody",
                }
            ],
            structured_facts={
                "query": "CD45 antibody",
                "match_status": "ok",
                "pricing_records": [
                    {
                        "catalog_no": "20081",
                        "name": "Anti-CD45 mAb",
                        "price": 350.0,
                        "currency": "USD",
                        "lead_time": "in stock",
                        "size": "100 ug",
                        "business_line": "antibody",
                    }
                ],
                "match_count": 1,
            },
        ),
    )

    with patch(
        "src.responser.csr.draft_llm.get_llm",
        return_value=_FakeStructuredLLM(
            "CD45 mAb (20081) is $350 USD per 100 ug, currently in stock."
        ),
    ):
        response = render_csr_draft_response(
            ResponseInput(
                query="How much is your CD45 antibody?",
                execution_result=_empty_execution_result(executed_calls=[pricing_call]),
            ),
            ResponsePlan(answer_focus="commercial_or_operational_lookup"),
        )

    block_types = [block.block_type for block in response.content_blocks]
    assert "structured_facts" in block_types

    draft_block = next(b for b in response.content_blocks if b.block_type == "csr_draft")
    assert draft_block.data["structured_record_count"] == 1

    structured_block = next(b for b in response.content_blocks if b.block_type == "structured_facts")
    assert structured_block.data["records"][0]["catalog_no"] == "20081"
    assert structured_block.data["records"][0]["_source_tool"] == "pricing_lookup_tool"

    # Slack-style section appears in the message body
    assert "*💰 Live catalog / pricing facts*" in response.message
    assert "20081" in response.message
    assert "350" in response.message

    # Live data alone is enough to ground the draft
    assert response.debug_info["grounding_status"] == "grounded"
    assert response.debug_info["structured_records_returned"] == 1
    trust_block = next(b for b in response.content_blocks if b.block_type == "trust_signal")
    assert trust_block.data["has_live_data"] is True
