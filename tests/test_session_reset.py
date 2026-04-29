from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api_models import AgentRequest, ConversationMessage
from src.app import service as app_service
from src.common.execution_models import ExecutionResult
from src.common.models import DemandProfile
from src.ingestion.models import (
    IngestionBundle,
    ParserContext,
    ParserRequestFlags,
    ParserSignals,
    TurnCore,
    TurnSignals,
)
from src.memory.models import MemoryContext, MemorySnapshot
from src.objects.models import ResolvedObjectState
from src.responser.models import ComposedResponse, ResponseBundle, ResponsePlan
from src.routing.models import DialogueActResult, RouteDecision


class _FakeSessionStore:
    def __init__(self) -> None:
        self.cleared_thread_ids: list[str | None] = []

    def clear_session(self, thread_id: str | None) -> None:
        self.cleared_thread_ids.append(thread_id)

    def load_session(self, thread_id: str | None):
        if self.cleared_thread_ids:
            return {
                "thread_id": thread_id,
                "recent_turns": [],
                "memory_snapshot": {},
                "updated_at": "",
            }
        return {
            "thread_id": thread_id,
            "recent_turns": [{"role": "assistant", "content": "old draft", "metadata": {}}],
            "memory_snapshot": {"thread_memory": {"active_route": "execute"}},
            "updated_at": "",
        }

    def load_memory_snapshot(self, thread_id: str | None):
        if self.cleared_thread_ids:
            return {}
        return {"thread_memory": {"active_route": "execute"}}


def test_load_session_context_resets_persisted_history_when_starting_new_conversation(monkeypatch) -> None:
    fake_store = _FakeSessionStore()
    monkeypatch.setattr(app_service, "SessionStore", lambda: fake_store)

    request = AgentRequest(
        thread_id="thread-123",
        user_query="new inquiry",
        start_new_conversation=True,
        conversation_history=[
            ConversationMessage(role="user", content="fresh turn"),
        ],
    )

    _store, memory_snapshot, merged_history, attachments = app_service._load_session_context(request)

    assert fake_store.cleared_thread_ids == ["thread-123"]
    assert memory_snapshot == {}
    assert merged_history == [{"role": "user", "content": "fresh turn", "metadata": {}}]
    assert attachments == []


def test_load_session_context_keeps_persisted_history_by_default(monkeypatch) -> None:
    fake_store = _FakeSessionStore()
    monkeypatch.setattr(app_service, "SessionStore", lambda: fake_store)

    request = AgentRequest(
        thread_id="thread-123",
        user_query="follow up",
        conversation_history=[
            ConversationMessage(role="user", content="fresh turn"),
        ],
    )

    _store, _memory_snapshot, merged_history, _attachments = app_service._load_session_context(request)

    assert fake_store.cleared_thread_ids == []
    assert merged_history[0]["content"] == "old draft"
    assert merged_history[1]["content"] == "fresh turn"


def test_run_email_agent_start_new_conversation_drops_persisted_history_before_ingestion(monkeypatch) -> None:
    fake_store = _FakeSessionStore()
    monkeypatch.setattr(app_service, "SessionStore", lambda: fake_store)

    seen: dict[str, object] = {}

    def fake_recall(*, thread_id: str, user_query: str, prior_state):
        seen["recall_prior_state"] = prior_state
        return MemoryContext(snapshot=MemorySnapshot())

    def fake_build_ingestion_bundle(*, thread_id: str, user_query: str, conversation_history, attachments, memory_context):
        seen["conversation_history"] = list(conversation_history)
        return IngestionBundle(
            turn_core=TurnCore(thread_id=thread_id, raw_query=user_query, normalized_query=user_query),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(
                    context=ParserContext(semantic_intent="general_info"),
                    request_flags=ParserRequestFlags(),
                )
            ),
            memory_context=memory_context,
        )

    class _FakeAgentState:
        def __init__(self) -> None:
            self.primary_route_decision = RouteDecision(
                action="execute",
                dialogue_act=DialogueActResult(act="inquiry", confidence=1.0),
                reason="ok",
            )
            self.primary_dialogue_act = self.primary_route_decision.dialogue_act
            self.primary_clarification = None
            self.overall_action = "execute"
            self.outcomes = []
            self.merged_execution_result = ExecutionResult(final_status="ok", reason="ok")

        def debug_summary(self) -> dict[str, object]:
            return {}

    def fake_build_response_bundle(_response_input):
        return ResponseBundle(
            composed_response=ComposedResponse(
                message="draft",
                response_type="csr_draft",
                content_blocks=[],
                debug_info={},
            ),
            response_plan=ResponsePlan(answer_focus="knowledge_lookup"),
            response_topic="knowledge_lookup",
            response_content_summary="",
            response_path="csr_renderer_direct",
        )

    def fake_persist_session_state(*args, **kwargs):
        return {"role": "assistant", "content": "draft", "metadata": {}}

    def fake_assemble_agent_response(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(app_service, "recall", fake_recall)
    monkeypatch.setattr(app_service, "build_ingestion_bundle", fake_build_ingestion_bundle)
    monkeypatch.setattr(app_service, "resolve_objects", lambda *args, **kwargs: ResolvedObjectState())
    monkeypatch.setattr(app_service, "assemble_intent_groups", lambda *args, **kwargs: [])
    monkeypatch.setattr(app_service, "build_demand_profile", lambda *args, **kwargs: DemandProfile())
    monkeypatch.setattr(app_service, "_run_agent_loop", lambda *args, **kwargs: _FakeAgentState())
    monkeypatch.setattr(app_service, "build_response_bundle", fake_build_response_bundle)
    monkeypatch.setattr(app_service, "_persist_session_state", fake_persist_session_state)
    monkeypatch.setattr(app_service, "_assemble_agent_response", fake_assemble_agent_response)

    request = AgentRequest(
        thread_id="thread-123",
        user_query="fresh inquiry",
        start_new_conversation=True,
        conversation_history=[ConversationMessage(role="user", content="fresh turn")],
    )

    response = app_service.run_email_agent(request)

    assert response == {"ok": True}
    assert fake_store.cleared_thread_ids == ["thread-123"]
    assert seen["recall_prior_state"] == {}
    assert seen["conversation_history"] == [
        {"role": "user", "content": "fresh turn", "metadata": {}}
    ]
