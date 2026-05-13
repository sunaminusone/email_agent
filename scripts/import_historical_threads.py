#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - depends on local environment
    psycopg = None
    Jsonb = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV_PATH = ROOT / "data" / "processed" / "hubspot_form_inquiries_long.csv"

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


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def normalize_text(value: Any) -> str:
    return clean_text(value).lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import historical HubSpot form-inquiry threads into PostgreSQL."
    )
    parser.add_argument(
        "--csv-path",
        default=str(DEFAULT_CSV_PATH),
        help="CSV source path. Defaults to data/processed/hubspot_form_inquiries_long.csv.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection string. Falls back to DATABASE_URL / PG* env vars.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to PostgreSQL. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--limit-threads",
        type=int,
        default=None,
        help="Cap the number of grouped threads processed (smoke test).",
    )
    return parser.parse_args()


def get_connection_string(explicit_value: str | None) -> str:
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


def _split_attachments(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    values: list[str] = []
    for chunk in text.replace("\n", ",").split(","):
        token = clean_text(chunk)
        if token:
            values.append(token)
    return values


@dataclass
class PreparedData:
    thread_rows: list[dict[str, Any]]
    message_rows_by_thread: dict[str, list[dict[str, Any]]]


def _sort_group_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    def sort_key(row: dict[str, str]) -> tuple[int, str, str]:
        raw_index = clean_text(row.get("reply_index"))
        try:
            reply_index = int(raw_index)
        except ValueError:
            reply_index = 0
        reply_timestamp = clean_text(row.get("reply_timestamp"))
        reply_message_id = clean_text(row.get("reply_message_id"))
        return (reply_index, reply_timestamp, reply_message_id)

    return sorted(rows, key=sort_key)


def _prepare_thread(thread_id: str, rows: list[dict[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ordered_rows = _sort_group_rows(rows)
    seed = ordered_rows[0]

    messages: list[dict[str, Any]] = []
    message_index = 0

    original_message = clean_text(seed.get("original_message"))
    submitted_at = clean_text(seed.get("submitted_at")) or None
    sender_name = clean_text(seed.get("sender_name")) or None
    sender_email = clean_text(seed.get("email")) or None

    if original_message:
        messages.append(
            {
                "thread_id": thread_id,
                "message_index": message_index,
                "role": "customer",
                "source": "form_submission",
                "timestamp": submitted_at,
                "sender_name": sender_name,
                "sender_email": sender_email,
                "subject": None,
                "direction": None,
                "body": original_message,
                "attachments": jsonb([]),
                "external_message_id": None,
            }
        )
        message_index += 1

    seen_customer_keys: set[tuple[str, str]] = set()
    if original_message:
        seen_customer_keys.add(("form_submission", normalize_text(original_message)))

    first_reply_at: str | None = None
    last_message_at: str | None = submitted_at

    for row in ordered_rows:
        customer_body = clean_text(row.get("customer_message"))
        customer_source = clean_text(row.get("customer_message_source")) or "customer_email"
        reply_body = clean_text(row.get("reply_message"))
        reply_timestamp = clean_text(row.get("reply_timestamp")) or None
        reply_sender_name = clean_text(row.get("reply_sender_name")) or None
        reply_sender_email = clean_text(row.get("reply_sender_email")) or None
        reply_subject = clean_text(row.get("reply_subject")) or None
        reply_direction = clean_text(row.get("reply_direction")) or None
        reply_message_id = clean_text(row.get("reply_message_id")) or None

        if customer_body:
            customer_key = (customer_source, normalize_text(customer_body))
            if customer_key not in seen_customer_keys:
                seen_customer_keys.add(customer_key)
                messages.append(
                    {
                        "thread_id": thread_id,
                        "message_index": message_index,
                        "role": "customer",
                        "source": customer_source,
                        "timestamp": None,
                        "sender_name": sender_name,
                        "sender_email": sender_email,
                        "subject": None,
                        "direction": None,
                        "body": customer_body,
                        "attachments": jsonb([]),
                        "external_message_id": None,
                    }
                )
                message_index += 1

        if reply_body:
            attachments = _split_attachments(row.get("reply_attachments", ""))
            messages.append(
                {
                    "thread_id": thread_id,
                    "message_index": message_index,
                    "role": "sales",
                    "source": "crm_email",
                    "timestamp": reply_timestamp,
                    "sender_name": reply_sender_name,
                    "sender_email": reply_sender_email,
                    "subject": reply_subject,
                    "direction": reply_direction,
                    "body": reply_body,
                    "attachments": jsonb(attachments),
                    "external_message_id": reply_message_id,
                }
            )
            message_index += 1
            if reply_timestamp and first_reply_at is None:
                first_reply_at = reply_timestamp
            if reply_timestamp:
                last_message_at = reply_timestamp

    thread_row = {
        "thread_id": thread_id,
        "submission_id": thread_id,
        "contact_id": clean_text(seed.get("contact_id")) or None,
        "submitted_at": submitted_at,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "institution": clean_text(seed.get("institution")) or None,
        "phone": clean_text(seed.get("phone")) or None,
        "service_of_interest": clean_text(seed.get("service_of_interest")) or None,
        "products_of_interest": clean_text(seed.get("products_of_interest")) or None,
        "how_did_you_hear": clean_text(seed.get("how_did_you_hear")) or None,
        "lifecycle_stage": clean_text(seed.get("lifecycle_stage")) or None,
        "form_name": clean_text(seed.get("form_name")) or None,
        "contact_owner_id": clean_text(seed.get("contact_owner_id")) or None,
        "contact_owner_name": clean_text(seed.get("contact_owner_name")) or None,
        "original_message": original_message or None,
        "message_count": len(messages),
        "first_reply_at": first_reply_at,
        "last_message_at": last_message_at,
    }
    return thread_row, messages


def collect_rows(csv_path: Path, *, limit_threads: int | None = None) -> PreparedData:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            submission_id = clean_text(row.get("submission_id"))
            if not submission_id:
                continue
            grouped[submission_id].append(row)

    thread_rows: list[dict[str, Any]] = []
    message_rows_by_thread: dict[str, list[dict[str, Any]]] = {}

    for i, thread_id in enumerate(sorted(grouped.keys())):
        if limit_threads is not None and i >= limit_threads:
            break
        thread_row, message_rows = _prepare_thread(thread_id, grouped[thread_id])
        thread_rows.append(thread_row)
        message_rows_by_thread[thread_id] = message_rows

    return PreparedData(
        thread_rows=thread_rows,
        message_rows_by_thread=message_rows_by_thread,
    )


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

    total_threads = len(rows_by_thread)
    total_messages = 0

    with conn.cursor() as cur:
        for idx, (thread_id, rows) in enumerate(rows_by_thread.items(), start=1):
            cur.execute(delete_sql, (thread_id,))
            if not rows:
                if idx % 100 == 0 or idx == total_threads:
                    print(
                        f"  rebuilt messages for {idx}/{total_threads} threads "
                        f"(messages written so far: {total_messages})",
                        flush=True,
                    )
                continue
            values = [tuple(row.get(column) for column in MESSAGE_COLUMNS) for row in rows]
            cur.executemany(insert_sql, values)
            total_messages += len(values)
            if idx % 100 == 0 or idx == total_threads:
                print(
                    f"  rebuilt messages for {idx}/{total_threads} threads "
                    f"(messages written so far: {total_messages})",
                    flush=True,
                )


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    csv_path = Path(args.csv_path)
    prepared = collect_rows(csv_path, limit_threads=args.limit_threads)

    total_messages = sum(len(rows) for rows in prepared.message_rows_by_thread.values())

    if not args.apply:
        print(f"Dry run complete. Prepared {len(prepared.thread_rows)} thread rows.")
        print(f"Prepared {total_messages} message rows.")
        for sample in prepared.thread_rows[:3]:
            thread_id = sample["thread_id"]
            print()
            print(f"Thread: {thread_id}")
            print(
                f"  sender={sample.get('sender_email')} submitted_at={sample.get('submitted_at')} "
                f"messages={sample.get('message_count')}"
            )
            for message in prepared.message_rows_by_thread.get(thread_id, [])[:4]:
                print(
                    f"    [{message['message_index']:02d}] {message['role']} "
                    f"source={message.get('source')} body={json.dumps((message.get('body') or '')[:80])}"
                )
        print()
        print("Re-run with --apply to commit.")
        return

    if psycopg is None:
        raise RuntimeError(
            "psycopg is not installed. Run `pip install -r requirements.txt` first."
        )

    connection_string = get_connection_string(args.database_url)
    with psycopg.connect(connection_string) as conn:
        print(f"Upserting {len(prepared.thread_rows)} historical threads...", flush=True)
        upsert_threads(conn, prepared.thread_rows)
        print("Rebuilding historical thread messages...", flush=True)
        replace_messages(conn, prepared.message_rows_by_thread)
        conn.commit()

    print(
        f"Imported {len(prepared.thread_rows)} historical threads and "
        f"{total_messages} historical thread messages."
    )


if __name__ == "__main__":
    main()
