from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.settings import BASE_DIR
from src.data_sources.hubspot.service import (
    HubSpotClient,
    _clean_text,
    _parse_dt,
)

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None
    Jsonb = None


DEFAULT_SYNC_STATE_PATH = BASE_DIR / "data" / "processed" / "hubspot_incremental_sync_state.json"
DEFAULT_FORM_GUID = "7fcd4b55-c78d-4401-b9b3-0f7a30456c0d"

THREAD_COLUMNS = [
    "thread_id",
    "submission_id",
    "contact_id",
    "submitted_at",
    "sender_name",
    "sender_email",
    "institution",
    "phone",
    "service_of_interest",
    "products_of_interest",
    "how_did_you_hear",
    "lifecycle_stage",
    "form_name",
    "contact_owner_id",
    "contact_owner_name",
    "original_message",
    "message_count",
    "first_reply_at",
    "last_message_at",
]

MESSAGE_COLUMNS = [
    "thread_id",
    "message_index",
    "role",
    "source",
    "timestamp",
    "sender_name",
    "sender_email",
    "subject",
    "direction",
    "body",
    "attachments",
    "external_message_id",
]

def jsonb(value: Any) -> Any:
    if Jsonb is None:
        return value
    return Jsonb(value)


def build_connection_string(explicit_value: str | None = None) -> str:
    import os

    if explicit_value:
        return explicit_value

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    host = os.getenv("PGHOST")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    dbname = os.getenv("PGDATABASE")
    if not all([host, user, password, dbname]):
        raise ValueError(
            "Missing PostgreSQL config. Set DATABASE_URL or PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE."
        )
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _submission_sort_key(submission: dict[str, Any]) -> tuple[datetime, str]:
    submitted_at = str(submission.get("submitted_at", "") or "").strip()
    submission_id = str(submission.get("submission_id", "") or "").strip()
    if not submitted_at:
        submitted_at = "1970-01-01T00:00:00+00:00"
    return (_parse_dt(submitted_at), submission_id)


def _submission_id(submission: dict[str, Any]) -> str:
    return str(submission.get("submission_id", "") or "").strip()


def upsert_threads(conn: psycopg.Connection[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    placeholders = ", ".join(["%s"] * len(THREAD_COLUMNS))
    columns_sql = ", ".join(THREAD_COLUMNS)
    update_sql = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in THREAD_COLUMNS if column != "thread_id"
    )
    sql = f"""
        INSERT INTO historical_threads ({columns_sql})
        VALUES ({placeholders})
        ON CONFLICT (thread_id)
        DO UPDATE SET {update_sql}, updated_at = CURRENT_TIMESTAMP
    """
    values = [tuple(row.get(column) for column in THREAD_COLUMNS) for row in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, values)


def replace_messages(conn: psycopg.Connection[Any], rows_by_thread: dict[str, list[dict[str, Any]]]) -> None:
    if not rows_by_thread:
        return

    delete_sql = "DELETE FROM historical_thread_messages WHERE thread_id = %s"
    placeholders = ", ".join(["%s"] * len(MESSAGE_COLUMNS))
    columns_sql = ", ".join(MESSAGE_COLUMNS)
    insert_sql = f"""
        INSERT INTO historical_thread_messages ({columns_sql})
        VALUES ({placeholders})
    """

    with conn.cursor() as cur:
        for thread_id, rows in rows_by_thread.items():
            cur.execute(delete_sql, (thread_id,))
            if not rows:
                continue
            values = [tuple(row.get(column) for column in MESSAGE_COLUMNS) for row in rows]
            cur.executemany(insert_sql, values)


@dataclass(slots=True)
class SyncSummary:
    submissions_synced: int
    threads_prepared: int
    messages_prepared: int
    applied: bool
    since: str
    next_cursor: str
    state_path: str
    submission_summaries: list[dict[str, Any]]
    empty_thread_samples: list[dict[str, Any]]
    thread_type_counts: dict[str, int]
    cursor_submission_ids: list[str]


class HubSpotIncrementalSync:
    def __init__(
        self,
        *,
        client: HubSpotClient | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        self.client = client or HubSpotClient()
        self.state_path = Path(state_path) if state_path is not None else DEFAULT_SYNC_STATE_PATH

    def sync_to_postgres(
        self,
        *,
        database_url: str | None = None,
        since: str | None = None,
        form_guid: str = DEFAULT_FORM_GUID,
        submission_limit: int = 200,
        per_contact_email_limit: int = 100,
        apply: bool = False,
        persist_state: bool = True,
    ) -> SyncSummary:
        if not self.client.is_configured():
            raise RuntimeError("HubSpot client is not configured. Set HUBSPOT_ACCESS_TOKEN first.")

        state = _load_state(self.state_path)
        effective_since = str(since or state.get("last_sync_at") or "").strip()
        processed_ids_at_cursor = {
            str(value).strip()
            for value in (state.get("last_submission_ids_at_cursor") or [])
            if str(value).strip()
        }
        submissions = self.client.export_form_inquiries(
            form_guid=form_guid,
            since=effective_since or None,
            progress=False,
        )
        submissions = self._filter_already_processed_submissions(
            submissions,
            since=effective_since,
            processed_ids_at_cursor=processed_ids_at_cursor,
        )
        submissions.sort(key=_submission_sort_key)
        if submission_limit is not None:
            submissions = submissions[:submission_limit]

        thread_rows: list[dict[str, Any]] = []
        message_rows_by_thread: dict[str, list[dict[str, Any]]] = {}
        submission_summaries: list[dict[str, Any]] = []
        next_cursor = effective_since
        cursor_submission_ids: list[str] = []

        for submission in submissions:
            submitted_at = str(submission.get("submitted_at", "") or "").strip()
            submission_id = _submission_id(submission)
            if submitted_at and (not next_cursor or _parse_dt(submitted_at) > _parse_dt(next_cursor)):
                next_cursor = submitted_at
                cursor_submission_ids = [submission_id] if submission_id else []
            elif submitted_at and next_cursor and _parse_dt(submitted_at) == _parse_dt(next_cursor):
                if submission_id:
                    cursor_submission_ids.append(submission_id)

            built_threads = self._build_submission_threads(
                submission,
                per_contact_email_limit=per_contact_email_limit,
            )
            submission_summaries.append(self._summarize_submission_threads(submission, built_threads))
            for thread_row, message_rows in built_threads:
                thread_id = str(thread_row["thread_id"])
                message_rows_by_thread[thread_id] = message_rows
                existing_index = next(
                    (
                        index
                        for index, existing in enumerate(thread_rows)
                        if str(existing.get("thread_id", "") or "") == thread_id
                    ),
                    None,
                )
                if existing_index is None:
                    thread_rows.append(thread_row)
                else:
                    thread_rows[existing_index] = thread_row

        total_messages = sum(len(rows) for rows in message_rows_by_thread.values())
        empty_thread_samples = self._build_empty_thread_samples(thread_rows, message_rows_by_thread)
        thread_type_counts = self._build_thread_type_counts(thread_rows)
        final_cursor_ids = sorted(
            set(cursor_submission_ids) if cursor_submission_ids else (
                processed_ids_at_cursor if next_cursor == effective_since else set()
            )
        )

        if apply and thread_rows:
            if psycopg is None:
                raise RuntimeError("psycopg is not installed.")
            connection_string = build_connection_string(database_url)
            with psycopg.connect(connection_string) as conn:
                upsert_threads(conn, thread_rows)
                replace_messages(conn, message_rows_by_thread)
                conn.commit()

        if persist_state and apply:
            _save_state(
                self.state_path,
                {
                    "last_sync_at": next_cursor or effective_since or "",
                    "last_submission_ids_at_cursor": final_cursor_ids,
                    "last_run_at": _iso_utc_now(),
                    "last_submissions_synced": len(submissions),
                    "last_threads_prepared": len(thread_rows),
                    "last_messages_prepared": total_messages,
                },
            )

        return SyncSummary(
            submissions_synced=len(submissions),
            threads_prepared=len(thread_rows),
            messages_prepared=total_messages,
            applied=apply,
            since=effective_since,
            next_cursor=next_cursor or effective_since,
            state_path=str(self.state_path),
            submission_summaries=submission_summaries,
            empty_thread_samples=empty_thread_samples,
            thread_type_counts=thread_type_counts,
            cursor_submission_ids=final_cursor_ids,
        )

    def _filter_already_processed_submissions(
        self,
        submissions: list[dict[str, Any]],
        *,
        since: str,
        processed_ids_at_cursor: set[str],
    ) -> list[dict[str, Any]]:
        if not since or not processed_ids_at_cursor:
            return list(submissions)

        filtered: list[dict[str, Any]] = []
        cursor_dt = _parse_dt(since)
        for submission in submissions:
            submitted_at = str(submission.get("submitted_at", "") or "").strip()
            submission_id = _submission_id(submission)
            if not submitted_at or not submission_id:
                filtered.append(submission)
                continue
            if _parse_dt(submitted_at) == cursor_dt and submission_id in processed_ids_at_cursor:
                continue
            filtered.append(submission)
        return filtered

    def _build_submission_threads(
        self,
        submission: dict[str, Any],
        *,
        per_contact_email_limit: int,
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        contact_id = str(submission.get("contact_id", "") or "").strip()
        contact_email = str(submission.get("email", "") or "").strip()
        if not contact_id or not contact_email:
            return []

        message_rows = self._build_submission_message_rows(
            submission=submission,
            contact_email=contact_email,
            limit=per_contact_email_limit,
        )
        if not message_rows:
            return []
        thread_id = f"hubspot-form-{submission.get('submission_id', contact_id)}"
        thread_row = self._build_submission_thread_row(thread_id, submission, message_rows)
        return [(thread_row, message_rows)]

    def _build_submission_message_rows(
        self,
        *,
        submission: dict[str, Any],
        contact_email: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        original_message = _clean_scalar(submission.get("message"))
        submitted_at = str(submission.get("submitted_at", "") or "").strip() or None
        sender_name = _clean_scalar(submission.get("sender_name")) or None
        if original_message:
            rows.append(
                {
                    "role": "customer",
                    "source": "form_submission",
                    "timestamp": submitted_at,
                    "sender_name": sender_name,
                    "sender_email": contact_email or None,
                    "subject": None,
                    "direction": None,
                    "body": original_message,
                    "attachments": jsonb([]),
                    "external_message_id": None,
                }
            )
        thread_messages = list(submission.get("thread_messages") or [])[:limit]
        for message in sorted(thread_messages, key=lambda item: str(item.get("timestamp", "") or "")):
            body = _clean_text(message.get("text", ""))
            if not body:
                continue
            role = str(message.get("role", "") or "").strip() or "sales"
            rows.append(
                {
                    "role": role,
                    "source": str(message.get("source", "") or "hubspot_email_engagement"),
                    "timestamp": str(message.get("timestamp", "") or "") or None,
                    "sender_name": _clean_scalar(message.get("sender_name")) or (sender_name if role == "customer" else None),
                    "sender_email": _clean_scalar(message.get("sender_email")) or (contact_email if role == "customer" else None),
                    "subject": _clean_scalar(message.get("subject")) or None,
                    "direction": _clean_scalar(message.get("direction")) or None,
                    "body": body,
                    "attachments": jsonb(list(message.get("attachment_ids") or [])),
                    "external_message_id": str(message.get("message_id", "") or "") or None,
                }
            )
        return self._finalize_message_rows(rows)

    def _finalize_message_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        finalized: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            finalized.append(
                {
                    "thread_id": "",
                    "message_index": index,
                    **row,
                }
            )
        return finalized

    def _build_submission_thread_row(
        self,
        thread_id: str,
        submission: dict[str, Any],
        message_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for row in message_rows:
            row["thread_id"] = thread_id

        customer_messages = [row for row in message_rows if row.get("role") == "customer"]
        sales_messages = [row for row in message_rows if row.get("role") == "sales"]
        first_customer = customer_messages[0] if customer_messages else (message_rows[0] if message_rows else {})
        submitted_at = first_customer.get("timestamp")
        original_message = first_customer.get("body")
        first_reply_at = next((row.get("timestamp") for row in sales_messages if row.get("timestamp")), None)
        last_message_at = next((row.get("timestamp") for row in reversed(message_rows) if row.get("timestamp")), submitted_at)

        return {
            "thread_id": thread_id,
            "submission_id": str(submission.get("submission_id", "") or "").strip() or thread_id,
            "contact_id": str(submission.get("contact_id", "") or "").strip() or None,
            "submitted_at": submitted_at,
            "sender_name": _clean_scalar(submission.get("sender_name")) or None,
            "sender_email": _clean_scalar(submission.get("email")) or None,
            "institution": _clean_scalar(submission.get("institution")) or None,
            "phone": _clean_scalar(submission.get("phone")) or None,
            "service_of_interest": _clean_scalar(submission.get("service_of_interest")) or None,
            "products_of_interest": _clean_scalar(submission.get("products_of_interest")) or None,
            "how_did_you_hear": _clean_scalar(submission.get("how_did_you_hear")) or None,
            "lifecycle_stage": _clean_scalar(submission.get("lifecycle_stage")) or None,
            "form_name": _clean_scalar(submission.get("form_name")) or "hubspot_form_sync",
            "contact_owner_id": _clean_scalar(submission.get("contact_owner_id")) or None,
            "contact_owner_name": _clean_scalar(submission.get("contact_owner_name")) or None,
            "original_message": original_message,
            "message_count": len(message_rows),
            "first_reply_at": first_reply_at,
            "last_message_at": last_message_at,
        }

    def _summarize_submission_threads(
        self,
        submission: dict[str, Any],
        built_threads: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    ) -> dict[str, Any]:
        email = str(submission.get("email", "") or "").strip()
        contact_id = str(submission.get("contact_id", "") or "").strip()
        form_threads = 0
        thread_count = 0
        message_count = 0
        empty_threads = 0

        for thread_row, message_rows in built_threads:
            thread_count += 1
            message_count += len(message_rows)
            if not message_rows:
                empty_threads += 1
            thread_id = str(thread_row.get("thread_id", "") or "")
            if thread_id.startswith("hubspot-form-"):
                form_threads += 1

        return {
            "contact_id": contact_id,
            "email": email,
            "submitted_at": str(submission.get("submitted_at", "") or "").strip(),
            "thread_count": thread_count,
            "message_count": message_count,
            "form_threads": form_threads,
            "empty_threads": empty_threads,
        }

    def _build_empty_thread_samples(
        self,
        thread_rows: list[dict[str, Any]],
        message_rows_by_thread: dict[str, list[dict[str, Any]]],
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for thread_row in thread_rows:
            thread_id = str(thread_row.get("thread_id", "") or "")
            message_rows = message_rows_by_thread.get(thread_id, [])
            if message_rows:
                continue
            samples.append(
                {
                    "thread_id": thread_id,
                    "contact_id": thread_row.get("contact_id"),
                    "sender_email": thread_row.get("sender_email"),
                    "form_name": thread_row.get("form_name"),
                }
            )
            if len(samples) >= limit:
                break
        return samples

    def _build_thread_type_counts(self, thread_rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"form": 0, "email": 0, "conversation": 0, "other": 0}
        for thread_row in thread_rows:
            thread_id = str(thread_row.get("thread_id", "") or "")
            if thread_id.startswith("hubspot-form-"):
                counts["form"] += 1
            elif thread_id.startswith("hubspot-email-"):
                counts["email"] += 1
            elif thread_id.startswith("hubspot-conversation-"):
                counts["conversation"] += 1
            else:
                counts["other"] += 1
        return counts
