#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_sources.hubspot.sync import DEFAULT_FORM_GUID, DEFAULT_SYNC_STATE_PATH, HubSpotIncrementalSync


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally sync recent HubSpot form submissions and their reply chains into PostgreSQL historical thread tables."
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
        "--form-guid",
        default=DEFAULT_FORM_GUID,
        help="HubSpot form GUID to sync from.",
    )
    parser.add_argument(
        "--submission-limit",
        type=int,
        default=200,
        help="Maximum form submissions to process in one run.",
    )
    parser.add_argument(
        "--email-limit",
        type=int,
        default=100,
        help="Maximum reply-chain messages retained per submission.",
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
        form_guid=args.form_guid,
        submission_limit=args.submission_limit,
        per_contact_email_limit=args.email_limit,
        apply=args.apply,
        persist_state=True,
    )

    print(f"State path       : {summary.state_path}")
    print(f"Since            : {summary.since or '(full form submission scan within limit)'}")
    print(f"Next cursor      : {summary.next_cursor or '(unchanged)'}")
    print(f"Submissions synced: {summary.submissions_synced}")
    print(f"Threads prepared : {summary.threads_prepared}")
    print(f"Messages prepared: {summary.messages_prepared}")
    print(
        "Thread types     : "
        f"form={summary.thread_type_counts.get('form', 0)} "
        f"email={summary.thread_type_counts.get('email', 0)} "
        f"conversation={summary.thread_type_counts.get('conversation', 0)} "
        f"other={summary.thread_type_counts.get('other', 0)}"
    )
    print(f"Applied          : {summary.applied}")
    if not args.apply:
        if summary.submission_summaries:
            print()
            print("Top submissions by thread count:")
            for item in sorted(
                summary.submission_summaries,
                key=lambda row: (int(row.get("thread_count", 0)), int(row.get("message_count", 0))),
                reverse=True,
            )[:10]:
                print(
                    "  "
                    f"{item.get('email') or '(no email)'} "
                    f"[contact_id={item.get('contact_id') or '-'}] "
                    f"threads={item.get('thread_count', 0)} "
                    f"messages={item.get('message_count', 0)} "
                    f"form_threads={item.get('form_threads', 0)}"
                )
        sparse_submissions = [
            item for item in summary.submission_summaries if item.get("thread_count", 0) > item.get("message_count", 0)
        ]
        if sparse_submissions:
            print()
            print("Submissions with more threads than messages:")
            for item in sorted(
                sparse_submissions,
                key=lambda row: (int(row.get("thread_count", 0)) - int(row.get("message_count", 0))),
                reverse=True,
            )[:10]:
                print(
                    "  "
                    f"{item.get('email') or '(no email)'} "
                    f"threads={item.get('thread_count', 0)} "
                    f"messages={item.get('message_count', 0)} "
                    f"empty_threads={item.get('empty_threads', 0)}"
                )
        if summary.empty_thread_samples:
            print()
            print("Empty thread samples:")
            for item in summary.empty_thread_samples[:10]:
                print(
                    "  "
                    f"{item.get('thread_id')} "
                    f"contact_id={item.get('contact_id') or '-'} "
                    f"sender_email={item.get('sender_email') or '-'} "
                    f"source={item.get('form_name') or '-'}"
                )
        print("Dry run only. Re-run with --apply to write to PostgreSQL and persist the new cursor.")


if __name__ == "__main__":
    main()
