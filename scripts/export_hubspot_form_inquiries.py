"""Export raw HubSpot form-submission inquiries plus the subsequent reply chain.

For each form submission we capture the original inquiry plus every outbound
email our support team sent to that contact. This script writes the raw
structured export that downstream processing can reshape into training tables.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations import HubSpotClient


CONTACT_US_FORM_ID = "7fcd4b55-c78d-4401-b9b3-0f7a30456c0d"

CSV_COLUMNS = [
    "submitted_at",
    "sender_name",
    "email",
    "institution",
    "phone",
    "message",
    "response",
    "response_attachments",
    "service_of_interest",
    "products_of_interest",
    "how_did_you_hear",
    "lifecycle_stage",
    "form_name",
    "contact_id",
    "contact_owner_id",
    "contact_owner_name",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--form-guid", default=CONTACT_US_FORM_ID, help="Form GUID to export (default: Contact Us form).")
    parser.add_argument("--since", default=None, help="ISO timestamp filter; only keep submissions on/after this time.")
    parser.add_argument(
        "--out-jsonl",
        default="data/raw/hubspot_form_inquiries_raw.jsonl",
        help="Raw JSONL output path (structured, thread_messages array).",
    )
    parser.add_argument(
        "--out-csv",
        default="data/raw/hubspot_form_inquiries_raw.csv",
        help="Raw CSV output path (flat, sales messages merged into single cell).",
    )
    return parser.parse_args()


def _sales_messages(record: dict) -> list[dict]:
    return [message for message in record.get("thread_messages", []) or [] if message.get("role") == "sales"]


def format_response_block(record: dict) -> str:
    responses = _sales_messages(record)
    if not responses:
        return ""
    chunks: list[str] = []
    for response in responses:
        timestamp = response.get("timestamp", "")
        sender = response.get("sender_name") or response.get("sender_email") or "Unknown"
        subject = response.get("subject", "")
        text = response.get("text", "")
        attachments = response.get("attachment_ids") or []
        header = f"[{timestamp} {sender}] Subject: {subject}".rstrip()
        if attachments:
            header += f" [attachments: {', '.join(attachments)}]"
        chunks.append(f"{header}\n{text}")
    return "\n---\n".join(chunks)


def format_attachment_summary(record: dict) -> str:
    responses = _sales_messages(record)
    summaries: list[str] = []
    for response in responses:
        attachments = response.get("attachment_ids") or []
        if not attachments:
            continue
        timestamp = response.get("timestamp", "")
        summaries.append(f"{timestamp}: {','.join(attachments)}")
    return " | ".join(summaries)


def main() -> None:
    args = parse_args()
    client = HubSpotClient()

    print(f"Exporting form inquiries from form {args.form_guid}...", flush=True)
    records = client.export_form_inquiries(form_guid=args.form_guid, since=args.since, progress=True)
    print(f"Fetched {len(records)} submissions.", flush=True)

    jsonl_path = Path(args.out_jsonl)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote JSONL: {jsonl_path}")

    csv_path = Path(args.out_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in records:
            row = {column: record.get(column, "") for column in CSV_COLUMNS}
            row["response"] = format_response_block(record)
            row["response_attachments"] = format_attachment_summary(record)
            writer.writerow(row)
    print(f"Wrote CSV:   {csv_path}")


if __name__ == "__main__":
    main()
