from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations import HubSpotClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export inbound customer queries from HubSpot emails/conversations into JSONL for agent training."
    )
    parser.add_argument(
        "--contact-email",
        action="append",
        dest="contact_emails",
        default=[],
        help="Only export data for these contact email addresses. Repeatable.",
    )
    parser.add_argument(
        "--contact-limit",
        type=int,
        default=100,
        help="Maximum number of contacts to scan when no explicit contact emails are given.",
    )
    parser.add_argument(
        "--thread-limit",
        type=int,
        default=50,
        help="Maximum number of conversation threads to fetch per contact.",
    )
    parser.add_argument(
        "--message-limit",
        type=int,
        default=100,
        help="Maximum number of messages to fetch per conversation thread.",
    )
    parser.add_argument(
        "--emails-only",
        action="store_true",
        help="Only export CRM email engagement queries.",
    )
    parser.add_argument(
        "--conversations-only",
        action="store_true",
        help="Only export conversations inbox queries.",
    )
    parser.add_argument(
        "--out",
        default="data/processed/hubspot_training_queries.jsonl",
        help="Output JSONL path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    include_email_engagements = not args.conversations_only
    include_conversations = not args.emails_only
    if not include_email_engagements and not include_conversations:
        raise SystemExit("At least one source must remain enabled.")

    client = HubSpotClient()
    records = client.export_training_queries(
        contact_emails=args.contact_emails,
        contact_limit=args.contact_limit,
        per_contact_thread_limit=args.thread_limit,
        per_thread_message_limit=args.message_limit,
        include_email_engagements=include_email_engagements,
        include_conversations=include_conversations,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Exported {len(records)} HubSpot training queries to {out_path}")


if __name__ == "__main__":
    main()
