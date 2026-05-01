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
    def is_configured(self) -> bool:
        return True

    def export_form_inquiries(self, *, form_guid: str, since: str | None, progress: bool):
        assert form_guid == "test-form-guid"
        assert since == "2026-04-29T00:00:00+00:00"
        assert progress is False
        return [
            {
                "contact_id": "42",
                "submission_id": "sub-1",
                "submitted_at": "2026-04-30T12:00:00+00:00",
                "form_id": "test-form-guid",
                "form_name": "Contact Us",
                "sender_name": "Ada Lovelace",
                "email": "customer@example.com",
                "institution": "Analytical Engines",
                "phone": "123-456",
                "message": "Can you quote 5mg antibody production?",
                "products_of_interest": "Human IgG1",
                "service_of_interest": "Antibody production",
                "how_did_you_hear": "Google",
                "lifecycle_stage": "lead",
                "contact_owner_id": "owner-1",
                "contact_owner_name": "Tim Nguyen",
                "thread_messages": [
                    {
                        "message_id": "email-2",
                        "timestamp": "2026-04-30T13:00:00Z",
                        "role": "sales",
                        "source": "hubspot_email_engagement",
                        "subject": "Re: Need a quote",
                        "text": "We can help with that.",
                        "sender_name": "Tim Nguyen",
                        "sender_email": "sales@promab.com",
                        "direction": "EMAIL",
                        "owner_id": "owner-1",
                        "attachment_ids": ["att-1", "att-2"],
                    },
                    {
                        "message_id": "email-3",
                        "timestamp": "2026-04-30T14:00:00Z",
                        "role": "customer",
                        "source": "hubspot_email_engagement",
                        "subject": "Re: Need a quote",
                        "text": "Please also share your lead time.",
                        "sender_name": "Ada Lovelace",
                        "sender_email": "customer@example.com",
                        "direction": "INCOMING_EMAIL",
                        "owner_id": "",
                        "attachment_ids": [],
                    },
                ],
            }
        ]


class _CursorBoundaryHubSpotClient:
    def is_configured(self) -> bool:
        return True

    def export_form_inquiries(self, *, form_guid: str, since: str | None, progress: bool):
        assert form_guid == "test-form-guid"
        assert since == "2026-04-30T12:00:00+00:00"
        assert progress is False
        return [
            {
                "contact_id": "old-processed",
                "submission_id": "sub-processed",
                "submitted_at": "2026-04-30T12:00:00+00:00",
                "form_name": "Contact Us",
                "sender_name": "Old Customer",
                "email": "old@example.com",
                "institution": "",
                "phone": "",
                "message": "already synced",
                "products_of_interest": "",
                "service_of_interest": "",
                "how_did_you_hear": "",
                "lifecycle_stage": "",
                "contact_owner_id": "",
                "contact_owner_name": "",
                "thread_messages": [],
            },
            {
                "contact_id": "new-same-ts",
                "submission_id": "sub-new-same-ts",
                "submitted_at": "2026-04-30T12:00:00+00:00",
                "form_name": "Contact Us",
                "sender_name": "Boundary Customer",
                "email": "boundary@example.com",
                "institution": "",
                "phone": "",
                "message": "same timestamp, new submission",
                "products_of_interest": "",
                "service_of_interest": "",
                "how_did_you_hear": "",
                "lifecycle_stage": "",
                "contact_owner_id": "",
                "contact_owner_name": "",
                "thread_messages": [],
            },
            {
                "contact_id": "newer",
                "submission_id": "sub-newer",
                "submitted_at": "2026-04-30T13:00:00+00:00",
                "form_name": "Contact Us",
                "sender_name": "Newer Customer",
                "email": "newer@example.com",
                "institution": "",
                "phone": "",
                "message": "newer submission",
                "products_of_interest": "",
                "service_of_interest": "",
                "how_did_you_hear": "",
                "lifecycle_stage": "",
                "contact_owner_id": "",
                "contact_owner_name": "",
                "thread_messages": [],
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
        form_guid="test-form-guid",
        submission_limit=1,
        per_contact_email_limit=10,
        apply=False,
        persist_state=False,
    )

    assert summary.submissions_synced == 1
    assert summary.threads_prepared == 1
    assert summary.messages_prepared == 3
    assert summary.next_cursor == "2026-04-30T12:00:00+00:00"
    assert summary.thread_type_counts == {"form": 1, "email": 0, "conversation": 0, "other": 0}
    assert summary.empty_thread_samples == []
    assert summary.submission_summaries[0]["thread_count"] == 1
    assert summary.submission_summaries[0]["message_count"] == 3
    assert summary.submission_summaries[0]["form_threads"] == 1
    assert summary.cursor_submission_ids == ["sub-1"]
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
        form_guid="test-form-guid",
        submission_limit=1,
        per_contact_email_limit=10,
        apply=True,
        persist_state=True,
    )

    assert summary.applied is True
    assert len(captured_threads) == 1
    assert set(captured_messages.keys()) == {"hubspot-form-sub-1"}

    thread = captured_threads[0]
    assert thread["sender_email"] == "customer@example.com"
    assert thread["original_message"] == "Can you quote 5mg antibody production?"
    assert thread["first_reply_at"] == "2026-04-30T13:00:00Z"
    assert thread["message_count"] == 3
    assert thread["submission_id"] == "sub-1"

    messages = captured_messages["hubspot-form-sub-1"]
    assert [row["role"] for row in messages] == ["customer", "sales", "customer"]
    assert _unwrap_attachments(messages[1]["attachments"]) == ["att-1", "att-2"]
    assert messages[2]["body"] == "Please also share your lead time."

    assert saved_state["path"] == tmp_path / "hubspot-sync-state.json"
    assert saved_state["payload"]["last_sync_at"] == "2026-04-30T12:00:00+00:00"
    assert saved_state["payload"]["last_submission_ids_at_cursor"] == ["sub-1"]
    assert saved_state["payload"]["last_threads_prepared"] == 1
    assert saved_state["payload"]["last_messages_prepared"] == 3
    assert summary.thread_type_counts == {"form": 1, "email": 0, "conversation": 0, "other": 0}
    assert summary.cursor_submission_ids == ["sub-1"]


def test_incremental_sync_filters_already_processed_ids_at_cursor(monkeypatch, tmp_path):
    state_path = tmp_path / "hubspot-sync-state.json"
    state_path.write_text(
        '{"last_sync_at":"2026-04-30T12:00:00+00:00","last_submission_ids_at_cursor":["sub-processed"]}',
        encoding="utf-8",
    )

    syncer = HubSpotIncrementalSync(
        client=_CursorBoundaryHubSpotClient(),
        state_path=state_path,
    )
    summary = syncer.sync_to_postgres(
        form_guid="test-form-guid",
        submission_limit=1,
        per_contact_email_limit=10,
        apply=False,
        persist_state=False,
    )

    assert summary.submissions_synced == 1
    assert summary.next_cursor == "2026-04-30T12:00:00+00:00"
    assert summary.cursor_submission_ids == ["sub-new-same-ts"]
    assert summary.submission_summaries[0]["email"] == "boundary@example.com"
