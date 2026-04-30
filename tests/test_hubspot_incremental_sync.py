from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_sources.hubspot.sync import HubSpotIncrementalSync


def _unwrap_attachments(value):
    return getattr(value, "obj", value)


class _FakeHubSpotClient:
    def __init__(self) -> None:
        self._contacts_response = {
            "results": [
                {
                    "id": "42",
                    "properties": {
                        "email": "customer@example.com",
                        "firstname": "Ada",
                        "lastname": "Lovelace",
                        "hs_object_id": "42",
                        "company": "Analytical Engines",
                        "phone": "123-456",
                        "service_of_interest": "Antibody production",
                        "products_of_interest": "Human IgG1",
                        "hubspot_owner_id": "owner-1",
                        "lastmodifieddate": "2026-04-30T12:00:00+00:00",
                    },
                }
            ]
        }

    def is_configured(self) -> bool:
        return True

    def _request(self, method: str, path: str, *, params=None, json_payload=None):  # noqa: ANN001
        assert method == "POST"
        assert path == "/crm/v3/objects/contacts/search"
        return self._contacts_response

    def _fetch_email_engagements(self, contact_id: str, limit: int):  # noqa: ANN001
        assert contact_id == "42"
        assert limit == 10
        return [
            {
                "id": "email-1",
                "properties": {
                    "hs_timestamp": "2026-04-29T09:00:00Z",
                    "hs_email_direction": "INCOMING_EMAIL",
                    "hs_email_subject": "Need a quote",
                    "hs_email_text": "Can you quote 5mg antibody production?",
                    "hs_email_from_email": "customer@example.com",
                    "hs_email_from_firstname": "Ada",
                    "hs_email_from_lastname": "Lovelace",
                    "hs_attachment_ids": "att-1;att-2",
                },
            },
            {
                "id": "email-2",
                "properties": {
                    "hs_timestamp": "2026-04-29T10:00:00Z",
                    "hs_email_direction": "EMAIL",
                    "hs_email_subject": "Re: Need a quote",
                    "hs_email_text": "We can help with that.",
                    "hs_email_from_email": "sales@promab.com",
                    "hs_email_from_firstname": "Tim",
                    "hs_email_from_lastname": "Nguyen",
                    "hs_attachment_ids": "",
                },
            },
        ]

    def _fetch_conversation_thread_ids(self, *, email: str, limit: int):  # noqa: ANN001
        assert email == "customer@example.com"
        assert limit == 5
        return ["thread-9"]

    def _fetch_conversation_messages(self, thread_id: str, limit: int):  # noqa: ANN001
        assert thread_id == "thread-9"
        assert limit == 20
        return [
            {
                "id": "conv-1",
                "createdAt": "2026-04-29T11:00:00Z",
                "text": "Hi, how can we help?",
                "sender": {"actorId": "A-123"},
            },
            {
                "id": "conv-2",
                "createdAt": "2026-04-29T11:05:00Z",
                "text": "Please also share your lead time.",
                "sender": {"actorId": "V-456"},
            },
        ]


def test_incremental_sync_dry_run_builds_historical_threads(monkeypatch, tmp_path):
    captured_threads = []
    captured_messages = {}

    def fake_upsert_threads(conn, rows):  # noqa: ANN001
        captured_threads.extend(rows)

    def fake_replace_messages(conn, rows_by_thread):  # noqa: ANN001
        captured_messages.update(rows_by_thread)

    monkeypatch.setattr("src.data_sources.hubspot.sync.upsert_threads", fake_upsert_threads)
    monkeypatch.setattr("src.data_sources.hubspot.sync.replace_messages", fake_replace_messages)

    syncer = HubSpotIncrementalSync(
        client=_FakeHubSpotClient(),
        state_path=tmp_path / "hubspot-sync-state.json",
    )
    summary = syncer.sync_to_postgres(
        since="2026-04-29T00:00:00+00:00",
        contact_limit=1,
        per_contact_email_limit=10,
        per_contact_thread_limit=5,
        per_thread_message_limit=20,
        apply=False,
        persist_state=False,
    )

    assert summary.contacts_scanned == 1
    assert summary.threads_prepared == 2
    assert summary.messages_prepared == 4
    assert summary.next_cursor == "2026-04-30T12:00:00+00:00"
    assert captured_threads == []
    assert captured_messages == {}


def test_incremental_sync_apply_writes_rows_and_persists_state(monkeypatch, tmp_path):
    captured_threads = []
    captured_messages = {}
    saved_state = {}

    def fake_upsert_threads(conn, rows):  # noqa: ANN001
        captured_threads.extend(rows)

    def fake_replace_messages(conn, rows_by_thread):  # noqa: ANN001
        captured_messages.update(rows_by_thread)

    def fake_save_state(path, payload):  # noqa: ANN001
        saved_state["path"] = path
        saved_state["payload"] = payload

    class _FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def commit(self):
            return None

    monkeypatch.setattr("src.data_sources.hubspot.sync.upsert_threads", fake_upsert_threads)
    monkeypatch.setattr("src.data_sources.hubspot.sync.replace_messages", fake_replace_messages)
    monkeypatch.setattr("src.data_sources.hubspot.sync._save_state", fake_save_state)
    monkeypatch.setattr(
        "src.data_sources.hubspot.sync.psycopg",
        SimpleNamespace(connect=lambda _: _FakeConnection()),
    )

    syncer = HubSpotIncrementalSync(
        client=_FakeHubSpotClient(),
        state_path=tmp_path / "hubspot-sync-state.json",
    )
    summary = syncer.sync_to_postgres(
        database_url="postgresql://example",
        since="2026-04-29T00:00:00+00:00",
        contact_limit=1,
        per_contact_email_limit=10,
        per_contact_thread_limit=5,
        per_thread_message_limit=20,
        apply=True,
        persist_state=True,
    )

    assert summary.applied is True
    assert len(captured_threads) == 2
    assert set(captured_messages.keys()) == {
        "hubspot-email-42",
        "hubspot-conversation-thread-9",
    }

    email_thread = next(row for row in captured_threads if row["thread_id"] == "hubspot-email-42")
    assert email_thread["sender_email"] == "customer@example.com"
    assert email_thread["original_message"] == "Can you quote 5mg antibody production?"
    assert email_thread["first_reply_at"] == "2026-04-29T10:00:00Z"
    assert email_thread["message_count"] == 2

    email_messages = captured_messages["hubspot-email-42"]
    assert [row["role"] for row in email_messages] == ["customer", "sales"]
    assert _unwrap_attachments(email_messages[0]["attachments"]) == ["att-1", "att-2"]
    assert email_messages[1]["body"] == "We can help with that."

    conversation_messages = captured_messages["hubspot-conversation-thread-9"]
    assert [row["role"] for row in conversation_messages] == ["sales", "customer"]
    assert conversation_messages[1]["body"] == "Please also share your lead time."

    assert saved_state["path"] == tmp_path / "hubspot-sync-state.json"
    assert saved_state["payload"]["last_sync_at"] == "2026-04-30T12:00:00+00:00"
    assert saved_state["payload"]["last_threads_prepared"] == 2
    assert saved_state["payload"]["last_messages_prepared"] == 4
