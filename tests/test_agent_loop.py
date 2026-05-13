from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import agent_loop
from src.common.execution_models import ExecutedToolCall, ExecutionResult
from src.common.models import DemandProfile, GroupDemand, IntentGroup
from src.executor.models import ClarificationFromPaths
from src.ingestion.models import IngestionBundle, TurnCore
from src.memory.models import MemoryContext, MemorySnapshot
from src.objects.models import ObjectCandidate, ResolvedObjectState
from src.routing.models import ClarificationPayload, DialogueActResult, RouteDecision
from src.tools.models import ToolRequest, ToolResult


def _dummy_call(
    *,
    tool_name: str = "technical_rag_tool",
    status: str = "ok",
    confidence: dict[str, object] | None = None,
) -> ExecutedToolCall:
    return ExecutedToolCall(
        call_id="c1",
        tool_name=tool_name,
        status=status,
        request=ToolRequest(tool_name=tool_name, query="q"),
        result=ToolResult(
            tool_name=tool_name,
            status=status,
            structured_facts={"retrieval_confidence": confidence or {}},
        ),
    )


def _memory_context() -> MemoryContext:
    return MemoryContext(snapshot=MemorySnapshot())


def _ingestion_bundle() -> IngestionBundle:
    return IngestionBundle(turn_core=TurnCore(thread_id="thread-1", raw_query="q", normalized_query="q"))


def _intent_group(intent: str = "technical_question") -> IntentGroup:
    return IntentGroup(intent=intent, confidence=0.9)


def test_coerce_route_for_csr_turns_clarify_into_execute_note() -> None:
    route_decision = RouteDecision(
        action="clarify",
        dialogue_act=DialogueActResult(act="inquiry", confidence=1.0),
        clarification=ClarificationPayload(
            kind="product_selection",
            reason="ambiguous object",
            prompt="Which one?",
        ),
        reason="needs selection",
    )

    coerced = agent_loop._coerce_route_for_csr(route_decision)

    assert coerced.action == "execute"
    assert "AI_ROUTING_NOTE original_action=clarify" in coerced.reason
    assert "needs selection" in coerced.reason
    assert "clarification_reason=ambiguous object" in coerced.reason


def test_run_group_execution_execute_path_resolves_when_any_tool_call_succeeds(monkeypatch) -> None:
    import src.executor.engine as engine
    import src.executor.path_evaluation as path_evaluation
    import src.executor.tool_selector as tool_selector

    monkeypatch.setattr(
        engine,
        "build_execution_context",
        lambda **kwargs: SimpleNamespace(
            primary_object=SimpleNamespace(object_type="service")
        ),
    )
    monkeypatch.setattr(tool_selector, "select_tools", lambda context: ["sel"])
    monkeypatch.setattr(engine, "extract_available_params", lambda context, tool_call_cache: {})
    monkeypatch.setattr(
        path_evaluation,
        "evaluate_execution_paths",
        lambda selections, obj_type, available_params: SimpleNamespace(
            recommended_action="execute"
        ),
    )
    monkeypatch.setattr(
        agent_loop,
        "run_executor",
        lambda **kwargs: ExecutionResult(
            executed_calls=[_dummy_call(status="ok")],
            final_status="error",
            reason="tool recovered enough context",
        ),
    )

    route_decision = RouteDecision(action="execute")
    route_decision, execution_result, status = agent_loop._run_group_execution(
        ingestion_bundle=_ingestion_bundle(),
        resolved_object_state=ResolvedObjectState(),
        memory_context=_memory_context(),
        demand_profile=DemandProfile(),
        group=_intent_group(),
        scoped_demand=GroupDemand(intent="technical_question"),
        route_decision=route_decision,
        tool_call_cache=object(),
    )

    assert route_decision.action == "execute"
    assert execution_result.executed_calls[0].status == "ok"
    assert status == "resolved"


def test_run_group_execution_all_paths_insufficient_returns_clarify(monkeypatch) -> None:
    import src.executor.engine as engine
    import src.executor.path_evaluation as path_evaluation
    import src.executor.tool_selector as tool_selector

    monkeypatch.setattr(
        engine,
        "build_execution_context",
        lambda **kwargs: SimpleNamespace(
            primary_object=SimpleNamespace(object_type="service")
        ),
    )
    monkeypatch.setattr(tool_selector, "select_tools", lambda context: ["sel"])
    monkeypatch.setattr(engine, "extract_available_params", lambda context, tool_call_cache: {})
    monkeypatch.setattr(
        path_evaluation,
        "evaluate_execution_paths",
        lambda selections, obj_type, available_params: SimpleNamespace(
            recommended_action="clarify",
            clarification_context=ClarificationFromPaths(
                missing_by_path={"tool_x": ["catalog_no", "customer_name"]}
            ),
        ),
    )
    monkeypatch.setattr(path_evaluation, "find_resolution_provider", lambda path_eval, available: None)

    route_decision, execution_result, status = agent_loop._run_group_execution(
        ingestion_bundle=_ingestion_bundle(),
        resolved_object_state=ResolvedObjectState(),
        memory_context=_memory_context(),
        demand_profile=DemandProfile(),
        group=_intent_group(),
        scoped_demand=GroupDemand(intent="technical_question"),
        route_decision=RouteDecision(action="execute"),
        tool_call_cache=object(),
    )

    assert execution_result.reason == "all execution paths insufficient"
    assert route_decision.action == "clarify"
    assert route_decision.clarification is not None
    assert route_decision.clarification.kind == "path_evaluation"
    assert route_decision.clarification.missing_information == ["catalog_no", "customer_name"]
    assert status == "needs_clarification"


def test_run_agent_loop_coerces_route_and_records_each_group(monkeypatch) -> None:
    import src.agent.tool_call_cache as tool_call_cache_mod

    recorded: list[dict[str, object]] = []
    logged: list[str] = []

    monkeypatch.setattr(tool_call_cache_mod, "ToolCallCache", lambda: object())
    monkeypatch.setattr(
        agent_loop,
        "narrow_demand_profile",
        lambda demand_profile, group, **kwargs: GroupDemand(intent=group.intent),
    )
    monkeypatch.setattr(
        agent_loop,
        "route",
        lambda ingestion_bundle, resolved_object_state, focus_group, scoped_demand: RouteDecision(
            action="clarify",
            dialogue_act=DialogueActResult(act="selection", confidence=0.9),
            clarification=ClarificationPayload(reason="need product"),
            reason=f"route-for-{focus_group.intent}",
        ),
    )

    def fake_run_group_execution(**kwargs):
        assert kwargs["route_decision"].action == "execute"
        return (
            kwargs["route_decision"],
            ExecutionResult(executed_calls=[_dummy_call(status="ok")], final_status="ok"),
            "resolved",
        )

    monkeypatch.setattr(agent_loop, "_run_group_execution", fake_run_group_execution)
    monkeypatch.setattr(
        agent_loop,
        "_log_group_retrieval_confidence",
        lambda **kwargs: logged.append(kwargs["thread_id"]),
    )
    monkeypatch.setattr(
        agent_loop,
        "_record_group_outcome",
        lambda **kwargs: recorded.append(
            {
                "intent": kwargs["group"].intent,
                "action": kwargs["route_decision"].action,
                "status": kwargs["status"],
            }
        ),
    )

    state = agent_loop._run_agent_loop(
        intent_groups=[_intent_group("technical_question"), _intent_group("pricing_question")],
        demand_profile=DemandProfile(),
        ingestion_bundle=_ingestion_bundle(),
        resolved_object_state=ResolvedObjectState(),
        memory_context=_memory_context(),
    )

    assert state.outcomes == []
    assert logged == ["thread-1", "thread-1"]
    assert recorded == [
        {"intent": "technical_question", "action": "execute", "status": "resolved"},
        {"intent": "pricing_question", "action": "execute", "status": "resolved"},
    ]
