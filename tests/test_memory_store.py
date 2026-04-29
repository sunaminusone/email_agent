from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.models import ObjectRef
from src.memory.adapters.redis_store import RedisSessionAdapter
from src.memory.models import ClarificationMemory, MemorySnapshot, MemoryUpdate, ResponseMemory, ThreadMemory
from src.memory.session_store import SessionStore
from src.memory.store import apply_memory_update, load_memory_snapshot


def test_load_memory_snapshot_rehydrates_typed_families() -> None:
    snapshot = load_memory_snapshot(
        {
            "thread_memory": {"active_route": "execute", "active_business_line": "antibody"},
            "object_memory": {"active_object": {"object_type": "product", "identifier": "A100", "display_name": "CD3"}},
            "clarification_memory": {"pending_clarification_type": "product_selection"},
            "response_memory": {"revealed_attributes": ["identity"]},
        },
        thread_id="thread-1",
    )

    assert snapshot.thread_memory.thread_id == "thread-1"
    assert snapshot.thread_memory.active_route == "execute"
    assert snapshot.object_memory.active_object is not None
    assert snapshot.object_memory.active_object.identifier == "A100"
    assert snapshot.clarification_memory.pending_clarification_type == "product_selection"
    assert snapshot.response_memory.revealed_attributes == ["identity"]


def test_load_memory_snapshot_reads_canonical_memory_snapshot_wrapper() -> None:
    snapshot = load_memory_snapshot(
        {
            "memory_snapshot": {
                "thread_memory": {"active_route": "execute"},
                "object_memory": {"active_object": {"object_type": "product", "identifier": "A100"}},
            }
        },
        thread_id="thread-1",
    )

    assert snapshot.thread_memory.thread_id == "thread-1"
    assert snapshot.thread_memory.active_route == "execute"
    assert snapshot.object_memory.active_object is not None
    assert snapshot.object_memory.active_object.identifier == "A100"


def test_load_memory_snapshot_ignores_retired_legacy_fields() -> None:
    snapshot = load_memory_snapshot(
        {
            "memory_snapshot": {
                "thread_memory": {
                    "active_route": "execute",
                    "route_phase": "active",
                    "last_assistant_prompt_type": "answer",
                },
                "response_memory": {
                    "revealed_attributes": ["identity"],
                },
                "intent_memory": {
                    "prior_semantic_intent": "workflow_question",
                },
            }
        },
        thread_id="thread-1",
    )

    assert snapshot.thread_memory.thread_id == "thread-1"
    assert snapshot.thread_memory.active_route == "execute"
    assert snapshot.response_memory.revealed_attributes == ["identity"]
    assert snapshot.intent_memory.prior_semantic_intent == "workflow_question"


def test_apply_memory_update_sets_and_appends_explicit_fields() -> None:
    snapshot = MemorySnapshot(
        thread_memory=ThreadMemory(thread_id="thread-1"),
        response_memory=ResponseMemory(revealed_attributes=["identity"]),
    )

    updated = apply_memory_update(
        snapshot,
        MemoryUpdate(
            thread_memory=ThreadMemory(
                thread_id="thread-1",
                active_route="execute",
                active_business_line="antibody",
                last_user_goal="find CD3",
            ),
            set_active_object=ObjectRef(
                object_type="product",
                identifier="A100",
                display_name="CD3 Antibody",
                business_line="antibody",
            ),
            secondary_active_objects=[
                ObjectRef(
                    object_type="product",
                    identifier="A101",
                    display_name="CD4 Antibody",
                    business_line="antibody",
                )
            ],
            append_recent_objects=[
                ObjectRef(
                    object_type="product",
                    identifier="A100",
                    display_name="CD3 Antibody",
                    business_line="antibody",
                )
            ],
            candidate_object_sets=[{"query_value": "CD", "candidate_count": 2}],
            set_pending_clarification=ClarificationMemory(
                pending_clarification_type="product_selection",
                pending_candidate_options=["A100", "A101"],
                pending_question="Which product did you mean?",
            ),
            mark_revealed_attributes=["applications"],
            set_last_tool_results=[{"tool_name": "catalog_lookup_tool", "status": "ok"}],
            set_last_response_topics=["direct_answer"],
        ),
    )

    assert updated.thread_memory.active_route == "execute"
    assert updated.object_memory.active_object is not None
    assert updated.object_memory.active_object.identifier == "A100"
    assert len(updated.object_memory.secondary_active_objects) == 1
    assert len(updated.object_memory.recent_objects) == 1
    assert updated.object_memory.candidate_object_sets == [{"query_value": "CD", "candidate_count": 2}]
    assert updated.clarification_memory.pending_candidate_options == ["A100", "A101"]
    assert updated.response_memory.revealed_attributes == ["identity", "applications"]
    assert updated.response_memory.last_tool_results == [{"tool_name": "catalog_lookup_tool", "status": "ok"}]
    assert updated.response_memory.last_response_topics == ["direct_answer"]


def test_apply_memory_update_soft_reset_clears_current_topic_but_keeps_recent_objects() -> None:
    snapshot = MemorySnapshot(
        object_memory={
            "active_object": {"object_type": "product", "identifier": "A100", "display_name": "CD3"},
            "recent_objects": [{"object_type": "product", "identifier": "A100", "display_name": "CD3"}],
        },
        clarification_memory={
            "pending_clarification_type": "product_selection",
            "pending_candidate_options": ["A100", "A101"],
        },
        response_memory={
            "revealed_attributes": ["identity"],
            "last_tool_results": [{"tool_name": "catalog_lookup_tool"}],
            "last_response_topics": ["direct_answer"],
        },
    )

    updated = apply_memory_update(snapshot, MemoryUpdate(soft_reset_current_topic=True))

    assert updated.object_memory.active_object is None
    assert updated.object_memory.recent_objects[0].identifier == "A100"
    assert updated.object_memory.candidate_object_sets == []
    assert updated.clarification_memory.pending_clarification_type == ""
    assert updated.response_memory.revealed_attributes == []
    assert updated.response_memory.last_tool_results == []
    assert updated.response_memory.last_response_topics == ["direct_answer"]


def test_load_memory_snapshot_from_history_metadata_reads_memory_snapshot_key() -> None:
    metadata = {
        "memory_snapshot": {
            "thread_memory": {"active_route": "execute"},
            "object_memory": {"active_object": {"object_type": "product", "identifier": "A100"}},
        },
    }
    snapshot = load_memory_snapshot(metadata.get("memory_snapshot"))

    assert snapshot.thread_memory.active_route == "execute"
    assert snapshot.object_memory.active_object is not None
    assert snapshot.object_memory.active_object.identifier == "A100"


class _AdapterSpy:
    def __init__(self, payload):
        self.payload = payload
        self.saved: list[tuple[str | None, dict]] = []

    def is_configured(self) -> bool:
        return True

    def load(self, thread_id: str | None):
        return self.payload

    def save(self, thread_id: str | None, payload: dict[str, object]) -> None:
        self.saved.append((thread_id, payload))

    def delete(self, thread_id: str | None) -> None:
        return None

    def session_key(self, thread_id: str) -> str:
        return thread_id


def test_session_store_migrates_legacy_snapshot_on_read(monkeypatch) -> None:
    legacy_payload = {
        "thread_id": "thread-1",
        "recent_turns": [{"role": "user", "content": "hello", "metadata": {}}],
        "memory_snapshot": {
            "thread_memory": {
                "active_route": "execute",
                "route_phase": "active",
                "last_assistant_prompt_type": "answer",
            },
        },
        "updated_at": "2026-04-28T20:00:00+00:00",
    }
    adapter = _AdapterSpy(legacy_payload)
    monkeypatch.setattr(RedisSessionAdapter, "__init__", lambda self, settings: None)

    store = SessionStore()
    store.settings = {"is_configured": True}
    store.adapter = adapter

    snapshot = store.load_memory_snapshot("thread-1")

    assert snapshot.thread_memory.active_route == "execute"
    assert len(adapter.saved) == 1
    saved_thread_id, saved_payload = adapter.saved[0]
    assert saved_thread_id == "thread-1"
    assert saved_payload["recent_turns"] == legacy_payload["recent_turns"]
    assert saved_payload["memory_snapshot"]["thread_memory"] == {
        "thread_id": "thread-1",
        "active_route": "execute",
        "last_turn_type": "",
        "last_user_goal": "",
        "active_business_line": "",
    }
