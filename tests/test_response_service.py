from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.response.composer as composer_module

from src.execution.models import ExecutedToolCall, ExecutionPlan, ExecutionRun
from src.routing.models import ClarificationPayload, DialogueActResult, ExecutionIntent
from src.tools.models import ToolRequest, ToolResult
from src.response import ResponseInput, build_response_bundle, compose_response


def _empty_execution_run(
    *,
    query: str = "test",
    dialogue_act: DialogueActResult | None = None,
    needs_clarification: bool = False,
    handoff_required: bool = False,
    executed_calls: list[ExecutedToolCall] | None = None,
) -> ExecutionRun:
    intent = ExecutionIntent(
        query=query,
        dialogue_act=dialogue_act or DialogueActResult(),
        needs_clarification=needs_clarification,
        handoff_required=handoff_required,
    )
    plan = ExecutionPlan(intent=intent)
    return ExecutionRun(
        intent=intent,
        plan=plan,
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
            execution_run=_empty_execution_run(executed_calls=[executed_call]),
        )
    )

    assert plan.response_mode == "direct_answer"
    assert response.response_type == "answer"
    assert "CD3 Antibody" in response.message


def test_compose_response_returns_clarification_prompt() -> None:
    response, plan = compose_response(
        ResponseInput(
            query="that one",
            execution_run=_empty_execution_run(needs_clarification=True),
            route_name="clarification",
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
            execution_run=_empty_execution_run(
                dialogue_act=DialogueActResult(act="TERMINATE"),
            ),
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
            execution_run=_empty_execution_run(executed_calls=[executed_call]),
        )
    )

    assert bundle.response_resolution.answer_focus == "knowledge_lookup"
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
            execution_run=_empty_execution_run(executed_calls=[executed_call]),
        )
    )

    assert bundle.response_path == "deterministic"
    assert bundle.composed_response.debug_info["rewrite_applied"] is False
