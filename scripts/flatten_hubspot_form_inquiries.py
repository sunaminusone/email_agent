"""Transform raw HubSpot form inquiries into a processed long-form CSV/JSONL.

Input: the raw JSONL produced by `export_hubspot_form_inquiries.py` (one
record per form submission, with replies nested as an array).

Output: one row per outbound sales reply, with three core text columns:
- `original_message`: the first form submission
- `customer_message`: the customer message that immediately precedes this
  sales reply in the modeled thread
- `reply_message`: the sales message itself

Rules:
- first sales reply after the form submission: `customer_message = original_message`
- later sales follow-ups with no intervening customer turn: `customer_message = ""`
- if the customer replied in between, `customer_message` becomes that latest
  customer turn
- submissions with zero sales replies still produce one placeholder row unless
  `--skip-empty` is passed
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


CSV_COLUMNS = [
    "submission_id",
    "contact_id",
    "submitted_at",
    "sender_name",
    "email",
    "institution",
    "phone",
    "original_message",
    "customer_message",
    "customer_message_source",
    "reply_message",
    "service_of_interest",
    "products_of_interest",
    "how_did_you_hear",
    "lifecycle_stage",
    "form_name",
    "contact_owner_id",
    "contact_owner_name",
    "reply_index",
    "reply_total",
    "reply_timestamp",
    "reply_sender_name",
    "reply_sender_email",
    "reply_subject",
    "reply_direction",
    "reply_attachments",
    "reply_message_id",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in-jsonl",
        default="data/raw/hubspot_form_inquiries_raw.jsonl",
        help="Raw JSONL produced by export_hubspot_form_inquiries.py.",
    )
    parser.add_argument(
        "--out-csv",
        default="data/processed/hubspot_form_inquiries_long.csv",
        help="Processed long CSV output (one row per sales reply).",
    )
    parser.add_argument(
        "--out-jsonl",
        default="data/processed/hubspot_form_inquiries_long.jsonl",
        help="Processed long JSONL output (one record per sales reply).",
    )
    parser.add_argument(
        "--skip-empty",
        action="store_true",
        help="Drop submissions with zero replies instead of emitting a placeholder row.",
    )
    return parser.parse_args()


def build_base_row(record: dict) -> dict:
    return {
        "submission_id": record.get("submission_id", ""),
        "contact_id": record.get("contact_id", ""),
        "submitted_at": record.get("submitted_at", ""),
        "sender_name": record.get("sender_name", ""),
        "email": record.get("email", ""),
        "institution": record.get("institution", ""),
        "phone": record.get("phone", ""),
        "original_message": record.get("message", ""),
        "customer_message": "",
        "customer_message_source": "",
        "reply_message": "",
        "service_of_interest": record.get("service_of_interest", ""),
        "products_of_interest": record.get("products_of_interest", ""),
        "how_did_you_hear": record.get("how_did_you_hear", ""),
        "lifecycle_stage": record.get("lifecycle_stage", ""),
        "form_name": record.get("form_name", ""),
        "contact_owner_id": record.get("contact_owner_id", ""),
        "contact_owner_name": record.get("contact_owner_name", ""),
    }


def expand_record(record: dict, skip_empty: bool) -> list[dict]:
    base = build_base_row(record)
    original_message = str(base["original_message"] or "")
    messages = list(record.get("thread_messages") or [])
    rows: list[dict] = []
    sales_messages = [message for message in messages if str(message.get("role", "")) == "sales"]
    if not sales_messages:
        if skip_empty:
            return rows
        rows.append(
            {
                **base,
                "reply_index": 0,
                "reply_total": 0,
                "reply_timestamp": "",
                "reply_sender_name": "",
                "reply_sender_email": "",
                "reply_subject": "",
                "reply_direction": "",
                "reply_attachments": "",
                "reply_message_id": "",
            }
        )
        return rows

    total = len(sales_messages)
    for idx, message in enumerate(messages):
        if str(message.get("role", "")) != "sales":
            continue
        sales_index = sum(1 for prior in messages[: idx + 1] if str(prior.get("role", "")) == "sales")
        attachments = message.get("attachment_ids") or []
        customer_message, customer_message_source = _resolve_customer_message_for_sales_message(
            messages, idx, original_message
        )
        rows.append(
            {
                **base,
                "customer_message": customer_message,
                "customer_message_source": customer_message_source,
                "reply_message": message.get("text", ""),
                "reply_index": sales_index,
                "reply_total": total,
                "reply_timestamp": message.get("timestamp", ""),
                "reply_sender_name": message.get("sender_name", ""),
                "reply_sender_email": message.get("sender_email", ""),
                "reply_subject": message.get("subject", ""),
                "reply_direction": message.get("direction", ""),
                "reply_attachments": ",".join(attachments),
                "reply_message_id": message.get("message_id", ""),
            }
        )
    return rows


def _resolve_customer_message_for_sales_message(
    messages: list[dict], sales_index: int, original_message: str
) -> tuple[str, str]:
    if sales_index <= 0:
        return original_message, "form_submission"
    previous_message = messages[sales_index - 1]
    if str(previous_message.get("role", "")) != "customer":
        return "", ""
    if str(previous_message.get("source", "")) == "form_submission":
        return original_message, "form_submission"
    return str(previous_message.get("text", "") or ""), "customer_email"


def main() -> None:
    args = parse_args()

    in_path = Path(args.in_jsonl)
    if not in_path.exists():
        raise SystemExit(f"Input JSONL not found: {in_path}")

    csv_path = Path(args.out_csv)
    jsonl_path = Path(args.out_jsonl)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    total_submissions = 0
    total_rows = 0
    total_with_replies = 0
    total_without_replies = 0

    with csv_path.open("w", encoding="utf-8", newline="") as csv_handle, jsonl_path.open(
        "w", encoding="utf-8"
    ) as jsonl_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for line in in_path.open("r", encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            total_submissions += 1
            if any(str(message.get("role", "")) == "sales" for message in (record.get("thread_messages") or [])):
                total_with_replies += 1
            else:
                total_without_replies += 1

            for row in expand_record(record, skip_empty=args.skip_empty):
                writer.writerow(row)
                jsonl_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                total_rows += 1

    print(f"Submissions read:      {total_submissions}")
    print(f"  with replies:        {total_with_replies}")
    print(f"  without replies:     {total_without_replies}")
    print(f"Rows emitted:          {total_rows}")
    print(f"Wrote CSV:             {csv_path}")
    print(f"Wrote JSONL:           {jsonl_path}")


if __name__ == "__main__":
    main()
