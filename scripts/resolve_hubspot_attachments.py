"""Resolve HubSpot file IDs in the historical-threads CSV to file metadata.

Reads `data/processed/hubspot_form_inquiries_long.csv`, collects every unique
file_id appearing in the `reply_attachments` column, and calls the HubSpot
Files API v3 once per id to capture {name, extension, type, url, accessLevel,
size}. Results are written to `data/processed/hubspot_attachments_cache.json`.

Re-runnable: existing entries in the cache are skipped on subsequent runs, so
this can be invoked again after the upstream CSV grows.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_sources.hubspot.service import HubSpotClient  # noqa: E402

CSV_PATH = PROJECT_ROOT / "data" / "processed" / "hubspot_form_inquiries_long.csv"
CACHE_PATH = PROJECT_ROOT / "data" / "processed" / "hubspot_attachments_cache.json"

KEEP_FIELDS = ("id", "name", "extension", "type", "url", "accessLevel", "size")


def _split_attachment_ids(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    parts: list[str] = []
    for chunk in text.replace("\n", ",").split(","):
        token = chunk.strip()
        if token:
            parts.append(token)
    return parts


def collect_file_ids(csv_path: Path) -> list[str]:
    seen: set[str] = set()
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            for fid in _split_attachment_ids(row.get("reply_attachments", "")):
                seen.add(fid)
    return sorted(seen)


def load_cache(cache_path: Path) -> dict[str, dict]:
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_cache(cache_path: Path, cache: dict[str, dict]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def trim_record(payload: dict) -> dict:
    return {key: payload.get(key) for key in KEEP_FIELDS if payload.get(key) is not None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap the number of new file_ids to resolve this run.")
    parser.add_argument("--sleep", type=float, default=0.05,
                        help="Sleep between HubSpot calls to stay under rate limits.")
    parser.add_argument("--retry-missing", action="store_true",
                        help="Re-attempt file_ids previously cached as not_found.")
    args = parser.parse_args()

    if not CSV_PATH.exists():
        raise SystemExit(f"CSV not found: {CSV_PATH}")

    file_ids = collect_file_ids(CSV_PATH)
    print(f"Found {len(file_ids)} unique file_ids in {CSV_PATH.name}")

    cache = load_cache(CACHE_PATH)
    print(f"Loaded {len(cache)} cached entries from {CACHE_PATH.name}")

    pending: list[str] = []
    for fid in file_ids:
        entry = cache.get(fid)
        if entry is None:
            pending.append(fid)
        elif args.retry_missing and entry.get("status") == "not_found":
            pending.append(fid)

    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"Resolving {len(pending)} file_ids...")

    client = HubSpotClient()
    if not client.is_configured():
        raise SystemExit("HUBSPOT_ACCESS_TOKEN not set; cannot resolve attachments.")

    resolved = 0
    not_found = 0
    for index, fid in enumerate(pending, 1):
        try:
            payload = client.get_file_metadata(fid)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{index}/{len(pending)}] {fid} ERROR: {exc}", flush=True)
            save_cache(CACHE_PATH, cache)
            raise

        if payload is None:
            cache[fid] = {"id": fid, "status": "not_found"}
            not_found += 1
        else:
            cache[fid] = {**trim_record(payload), "status": "ok"}
            resolved += 1

        if index % 25 == 0:
            print(f"  [{index}/{len(pending)}] resolved={resolved} not_found={not_found}", flush=True)
            save_cache(CACHE_PATH, cache)
        if args.sleep:
            time.sleep(args.sleep)

    save_cache(CACHE_PATH, cache)
    print()
    print(f"Done. resolved={resolved} not_found={not_found} cache_total={len(cache)}")
    print(f"Wrote: {CACHE_PATH}")


if __name__ == "__main__":
    main()
