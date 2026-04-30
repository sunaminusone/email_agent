from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.settings import BASE_DIR
from src.data_sources.hubspot.service import (
    CONTACT_INQUIRY_PROPERTIES,
    CONTACT_PROPERTIES,
    HubSpotClient,
    _clean_text,
    _compose_name,
    _extract_latest_email_reply,
    _is_inbound_email,
    _parse_dt,
    _split_attachment_ids,
)

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None
    Jsonb = None


DEFAULT_SYNC_STATE_PATH = BASE_DIR / "data" / "processed" / "hubspot_incremental_sync_state.json"

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

SYNC_CONTACT_PROPERTIES = sorted(
    {
        *CONTACT_PROPERTIES,
        *CONTACT_INQUIRY_PROPERTIES,
        "lastmodifieddate",
    }
)


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
    contacts_scanned: int
    threads_prepared: int
    messages_prepared: int
    applied: bool
    since: str
    next_cursor: str
    state_path: str


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
        contact_limit: int = 200,
        per_contact_email_limit: int = 100,
        per_contact_thread_limit: int = 50,
        per_thread_message_limit: int = 100,
        apply: bool = False,
        persist_state: bool = True,
    ) -> SyncSummary:
        if not self.client.is_configured():
            raise RuntimeError("HubSpot client is not configured. Set HUBSPOT_ACCESS_TOKEN first.")

        state = _load_state(self.state_path)
        effective_since = str(since or state.get("last_sync_at") or "").strip()
        contacts = self._fetch_updated_contacts(
            since=effective_since or None,
            limit=contact_limit,
        )

        thread_rows: list[dict[str, Any]] = []
        message_rows_by_thread: dict[str, list[dict[str, Any]]] = {}
        next_cursor = effective_since

        for contact in contacts:
            properties = dict(contact.get("properties") or {})
            last_modified = str(properties.get("lastmodifieddate") or "").strip()
            if last_modified and (not next_cursor or _parse_dt(last_modified) > _parse_dt(next_cursor)):
                next_cursor = last_modified

            for thread_row, message_rows in self._build_contact_threads(
                contact,
                per_contact_email_limit=per_contact_email_limit,
                per_contact_thread_limit=per_contact_thread_limit,
                per_thread_message_limit=per_thread_message_limit,
            ):
                thread_id = str(thread_row["thread_id"])
                thread_rows.append(thread_row)
                message_rows_by_thread[thread_id] = message_rows

        total_messages = sum(len(rows) for rows in message_rows_by_thread.values())

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
                    "last_run_at": _iso_utc_now(),
                    "last_contacts_scanned": len(contacts),
                    "last_threads_prepared": len(thread_rows),
                    "last_messages_prepared": total_messages,
                },
            )

        return SyncSummary(
            contacts_scanned=len(contacts),
            threads_prepared=len(thread_rows),
            messages_prepared=total_messages,
            applied=apply,
            since=effective_since,
            next_cursor=next_cursor or effective_since,
            state_path=str(self.state_path),
        )

    def _fetch_updated_contacts(
        self,
        *,
        since: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        after: str | None = None

        while len(results) < limit:
            batch_limit = min(100, limit - len(results))
            payload: dict[str, Any] = {
                "properties": SYNC_CONTACT_PROPERTIES,
                "sorts": [{"propertyName": "lastmodifieddate", "direction": "ASCENDING"}],
                "limit": batch_limit,
            }
            if since:
                payload["filterGroups"] = [
                    {
                        "filters": [
                            {
                                "propertyName": "lastmodifieddate",
                                "operator": "GTE",
                                "value": since,
                            }
                        ]
                    }
                ]
            else:
                payload["filterGroups"] = []
            if after:
                payload["after"] = after

            response = self.client._request(  # noqa: SLF001
                "POST",
                "/crm/v3/objects/contacts/search",
                json_payload=payload,
            )
            batch = response.get("results", []) or []
            results.extend(batch)
            paging = response.get("paging", {}) or {}
            next_after = ((paging.get("next") or {}).get("after") or "").strip()
            if not batch or not next_after:
                break
            after = next_after

        return results[:limit]

    def _build_contact_threads(
        self,
        contact: dict[str, Any],
        *,
        per_contact_email_limit: int,
        per_contact_thread_limit: int,
        per_thread_message_limit: int,
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        properties = dict(contact.get("properties") or {})
        contact_id = str(contact.get("id", "") or "").strip()
        contact_email = str(properties.get("email", "") or "").strip()
        if not contact_id or not contact_email:
            return []

        results: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

        email_rows = self._build_email_engagement_rows(
            contact_id=contact_id,
            contact_email=contact_email,
            properties=properties,
            limit=per_contact_email_limit,
        )
        if email_rows:
            thread_id = f"hubspot-email-{contact_id}"
            results.append((self._build_thread_row(thread_id, properties, email_rows, form_name="hubspot_email_sync"), email_rows))

        thread_ids = self.client._fetch_conversation_thread_ids(  # noqa: SLF001
            email=contact_email,
            limit=per_contact_thread_limit,
        )
        for raw_thread_id in thread_ids:
            conversation_rows = self._build_conversation_rows(
                contact_id=contact_id,
                contact_email=contact_email,
                properties=properties,
                raw_thread_id=raw_thread_id,
                limit=per_thread_message_limit,
            )
            if not conversation_rows:
                continue
            thread_id = f"hubspot-conversation-{raw_thread_id}"
            results.append((self._build_thread_row(thread_id, properties, conversation_rows, form_name="hubspot_conversation_sync"), conversation_rows))

        return results

    def _build_email_engagement_rows(
        self,
        *,
        contact_id: str,
        contact_email: str,
        properties: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        messages = self.client._fetch_email_engagements(contact_id, limit)  # noqa: SLF001
        rows: list[dict[str, Any]] = []
        for message in sorted(messages, key=lambda item: str((item.get("properties") or {}).get("hs_timestamp") or "")):
            msg_props = dict(message.get("properties") or {})
            direction = str(msg_props.get("hs_email_direction", "") or "")
            sender_email = str(msg_props.get("hs_email_from_email", "") or "")
            body = _extract_latest_email_reply(
                msg_props.get("hs_email_text") or msg_props.get("hs_email_html") or ""
            )
            if not body:
                continue
            role = "customer" if _is_inbound_email(
                direction=direction,
                sender_email=sender_email,
                contact_email=contact_email,
            ) else "sales"
            rows.append(
                {
                    "role": role,
                    "source": "hubspot_email_engagement",
                    "timestamp": str(msg_props.get("hs_timestamp", "") or "") or None,
                    "sender_name": _compose_name(
                        msg_props.get("hs_email_from_firstname"),
                        msg_props.get("hs_email_from_lastname"),
                    ) or _compose_name(properties.get("firstname"), properties.get("lastname")) or None,
                    "sender_email": sender_email or None,
                    "subject": str(msg_props.get("hs_email_subject", "") or "") or None,
                    "direction": direction or None,
                    "body": body,
                    "attachments": jsonb(_split_attachment_ids(msg_props.get("hs_attachment_ids", ""))),
                    "external_message_id": str(message.get("id", "") or "") or None,
                }
            )
        return self._finalize_message_rows(rows)

    def _build_conversation_rows(
        self,
        *,
        contact_id: str,
        contact_email: str,
        properties: dict[str, Any],
        raw_thread_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        messages = self.client._fetch_conversation_messages(raw_thread_id, limit)  # noqa: SLF001
        rows: list[dict[str, Any]] = []
        for message in sorted(messages, key=lambda item: str(item.get("createdAt", "") or "")):
            body = _clean_text(message.get("text", ""))
            if not body:
                continue
            sender = dict(message.get("sender") or {})
            actor_id = str(sender.get("actorId", "") or "")
            role = "customer" if actor_id.startswith("V-") else "sales"
            rows.append(
                {
                    "role": role,
                    "source": "hubspot_conversation",
                    "timestamp": str(message.get("createdAt", "") or "") or None,
                    "sender_name": (
                        _compose_name(properties.get("firstname"), properties.get("lastname"))
                        if role == "customer"
                        else None
                    ),
                    "sender_email": contact_email if role == "customer" else None,
                    "subject": None,
                    "direction": None,
                    "body": body,
                    "attachments": jsonb([]),
                    "external_message_id": str(message.get("id", "") or "") or None,
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

    def _build_thread_row(
        self,
        thread_id: str,
        properties: dict[str, Any],
        message_rows: list[dict[str, Any]],
        *,
        form_name: str,
    ) -> dict[str, Any]:
        for row in message_rows:
            row["thread_id"] = thread_id

        sender_name = _compose_name(properties.get("firstname"), properties.get("lastname")) or None
        sender_email = str(properties.get("email", "") or "").strip() or None

        customer_messages = [row for row in message_rows if row.get("role") == "customer"]
        sales_messages = [row for row in message_rows if row.get("role") == "sales"]
        first_customer = customer_messages[0] if customer_messages else (message_rows[0] if message_rows else {})
        submitted_at = first_customer.get("timestamp")
        original_message = first_customer.get("body")
        first_reply_at = next((row.get("timestamp") for row in sales_messages if row.get("timestamp")), None)
        last_message_at = next((row.get("timestamp") for row in reversed(message_rows) if row.get("timestamp")), submitted_at)

        return {
            "thread_id": thread_id,
            "submission_id": thread_id,
            "contact_id": str(properties.get("hs_object_id", "") or "").strip() or None,
            "submitted_at": submitted_at,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "institution": _clean_scalar(properties.get("company")) or None,
            "phone": _clean_scalar(properties.get("phone")) or None,
            "service_of_interest": _clean_scalar(properties.get("service_of_interest")) or None,
            "products_of_interest": _clean_scalar(properties.get("products_of_interest")) or None,
            "how_did_you_hear": _clean_scalar(properties.get("how_did_you_hera_about_us_")) or None,
            "lifecycle_stage": _clean_scalar(properties.get("lifecyclestage")) or None,
            "form_name": form_name,
            "contact_owner_id": _clean_scalar(properties.get("hubspot_owner_id")) or None,
            "contact_owner_name": None,
            "original_message": original_message,
            "message_count": len(message_rows),
            "first_reply_at": first_reply_at,
            "last_message_at": last_message_at,
        }

