#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_sources.hubspot.sync import DEFAULT_SYNC_STATE_PATH, HubSpotIncrementalSync


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally sync updated HubSpot contacts, email engagements, and conversations into PostgreSQL historical thread tables."
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO timestamp lower bound. Defaults to the saved sync cursor.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection string. Falls back to DATABASE_URL / PG* env vars.",
    )
    parser.add_argument(
        "--state-path",
        default=str(DEFAULT_SYNC_STATE_PATH),
        help="Path to the sync state JSON file.",
    )
    parser.add_argument(
        "--contact-limit",
        type=int,
        default=200,
        help="Maximum updated contacts to scan in one run.",
    )
    parser.add_argument(
        "--email-limit",
        type=int,
        default=100,
        help="Maximum email engagements fetched per contact.",
    )
    parser.add_argument(
        "--thread-limit",
        type=int,
        default=50,
        help="Maximum conversation threads fetched per contact.",
    )
    parser.add_argument(
        "--message-limit",
        type=int,
        default=100,
        help="Maximum conversation messages fetched per thread.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to PostgreSQL and advance the saved sync cursor.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    syncer = HubSpotIncrementalSync(state_path=args.state_path)
    summary = syncer.sync_to_postgres(
        database_url=args.database_url,
        since=args.since,
        contact_limit=args.contact_limit,
        per_contact_email_limit=args.email_limit,
        per_contact_thread_limit=args.thread_limit,
        per_thread_message_limit=args.message_limit,
        apply=args.apply,
        persist_state=True,
    )

    print(f"State path       : {summary.state_path}")
    print(f"Since            : {summary.since or '(full contact scan within limit)'}")
    print(f"Next cursor      : {summary.next_cursor or '(unchanged)'}")
    print(f"Contacts scanned : {summary.contacts_scanned}")
    print(f"Threads prepared : {summary.threads_prepared}")
    print(f"Messages prepared: {summary.messages_prepared}")
    print(f"Applied          : {summary.applied}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write to PostgreSQL and persist the new cursor.")


if __name__ == "__main__":
    main()
