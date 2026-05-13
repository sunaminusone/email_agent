"""Build a clean one-row-per-submission first-inquiry export.

This is a stricter companion to `hubspot_form_inquiries_long.csv`.

Goals:
- keep the full long export intact for thread browsing
- produce a cleaner dataset for sample review / evaluation
- anchor each row to the original form submission plus the first sales reply

Output:
- one row per form submission
- `thread_first_inquiry` is always the original form message
- `thread_first_reply_text` is the first sales reply, if any
- audit flags help spot rows that are likely internal/test/noisy
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LONG_CSV = "data/processed/hubspot_form_inquiries_long.csv"
DEFAULT_RAW_JSONL = "data/raw/hubspot_form_inquiries_raw.jsonl"
DEFAULT_OUT_CSV = "data/processed/production_conversation_first_inquiries_clean.csv"

OUTPUT_COLUMNS = [
    "submission_id",
    "contact_id",
    "submitted_at",
    "sender_name",
    "email",
    "institution",
    "service_of_interest",
    "products_of_interest",
    "customer_message_source",
    "reply_subject",
    "thread_first_inquiry",
    "thread_first_reply_text",
    "reply_total",
    "first_reply_delay_days",
    "crm_subject_count",
    "has_customer_before_first_sales",
    "sample_quality",
    "quality_notes",
    "source_row_index",
]

TEST_PATTERNS = [
    re.compile(r"\btest\b", re.IGNORECASE),
    re.compile(r"\bnotification\b", re.IGNORECASE),
]

INTERNAL_DOMAINS = {"promab.com", "theteam247.com", "psglifesciences.com"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-long-csv", default=DEFAULT_LONG_CSV)
    parser.add_argument("--in-raw-jsonl", default=DEFAULT_RAW_JSONL)
    parser.add_argument("--out-csv", default=DEFAULT_OUT_CSV)
    return parser.parse_args()


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _email_domain(email: str) -> str:
    text = str(email or "").strip().lower()
    if "@" not in text:
        return ""
    return text.rsplit("@", 1)[-1]


def _looks_like_test(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in TEST_PATTERNS)


def _load_thread_audit(raw_jsonl_path: Path) -> dict[str, dict[str, Any]]:
    audit: dict[str, dict[str, Any]] = {}
    with raw_jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            submission_id = str(record.get("submission_id", "")).strip()
            messages = list(record.get("thread_messages") or [])
            sales_indexes = [idx for idx, message in enumerate(messages) if str(message.get("role", "")) == "sales"]
            first_sales_idx = sales_indexes[0] if sales_indexes else None
            crm_subjects = [
                str(message.get("subject", "") or "").strip()
                for message in messages
                if str(message.get("source", "")) == "crm_email" and str(message.get("subject", "") or "").strip()
            ]
            submitted_at = _parse_iso(str(record.get("submitted_at", "") or ""))
            first_sales_at = _parse_iso(str(messages[first_sales_idx].get("timestamp", "") or "")) if first_sales_idx is not None else None
            delay_days = ""
            if submitted_at is not None and first_sales_at is not None:
                delay_days = round((first_sales_at - submitted_at).total_seconds() / 86400, 1)
            has_customer_before_first_sales = False
            if first_sales_idx is not None:
                has_customer_before_first_sales = any(
                    str(message.get("role", "")) == "customer" and str(message.get("source", "")) == "crm_email"
                    for message in messages[:first_sales_idx]
                )
            audit[submission_id] = {
                "crm_subject_count": len(set(crm_subjects)),
                "has_customer_before_first_sales": has_customer_before_first_sales,
                "first_reply_delay_days": delay_days,
            }
    return audit


def _quality_for_row(row: dict[str, str], audit: dict[str, Any]) -> tuple[str, str]:
    notes: list[str] = []
    quality = "qualified"

    original_message = str(row.get("thread_first_inquiry", "") or "")
    reply_text = str(row.get("thread_first_reply_text", "") or "")
    domain = _email_domain(str(row.get("email", "") or ""))

    if not reply_text:
        quality = "no_reply"
        notes.append("no sales reply")

    if domain in INTERNAL_DOMAINS:
        quality = "needs_review"
        notes.append(f"internal_or_partner_domain:{domain}")

    if _looks_like_test(original_message):
        quality = "needs_review"
        notes.append("looks_like_test_message")

    if audit.get("has_customer_before_first_sales"):
        quality = "needs_review"
        notes.append("customer_replied_before_first_sales")

    delay_days = audit.get("first_reply_delay_days", "")
    if isinstance(delay_days, (int, float)) and delay_days > 14:
        quality = "needs_review"
        notes.append(f"long_first_reply_delay:{delay_days}d")

    subject_count = int(audit.get("crm_subject_count", 0) or 0)
    if subject_count > 3:
        if quality == "qualified":
            quality = "review_recommended"
        notes.append(f"many_subjects:{subject_count}")

    return quality, "; ".join(notes)


def build_clean_export(long_csv_path: Path, raw_jsonl_path: Path, out_csv_path: Path) -> Path:
    audit_by_submission = _load_thread_audit(raw_jsonl_path)

    rows_out: list[dict[str, Any]] = []
    with long_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if str(row.get("reply_index", "") or "") not in {"0", "1"}:
                continue

            submission_id = str(row.get("submission_id", "") or "").strip()
            audit = audit_by_submission.get(submission_id, {})
            record = {
                "submission_id": submission_id,
                "contact_id": row.get("contact_id", ""),
                "submitted_at": row.get("submitted_at", ""),
                "sender_name": row.get("sender_name", ""),
                "email": row.get("email", ""),
                "institution": row.get("institution", ""),
                "service_of_interest": row.get("service_of_interest", ""),
                "products_of_interest": row.get("products_of_interest", ""),
                "customer_message_source": row.get("customer_message_source", ""),
                "reply_subject": row.get("reply_subject", ""),
                "thread_first_inquiry": row.get("original_message", ""),
                "thread_first_reply_text": row.get("reply_message", ""),
                "reply_total": row.get("reply_total", ""),
                "first_reply_delay_days": audit.get("first_reply_delay_days", ""),
                "crm_subject_count": audit.get("crm_subject_count", 0),
                "has_customer_before_first_sales": audit.get("has_customer_before_first_sales", False),
                "sample_quality": "",
                "quality_notes": "",
                "source_row_index": index,
            }
            quality, notes = _quality_for_row(record, audit)
            record["sample_quality"] = quality
            record["quality_notes"] = notes
            rows_out.append(record)

    out_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with out_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows_out)

    return out_csv_path


def main() -> None:
    args = parse_args()
    out_path = build_clean_export(
        long_csv_path=Path(args.in_long_csv),
        raw_jsonl_path=Path(args.in_raw_jsonl),
        out_csv_path=Path(args.out_csv),
    )
    print(f"Wrote CSV: {out_path}")


if __name__ == "__main__":
    main()
