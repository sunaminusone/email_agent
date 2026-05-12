"""Phase 0 baseline snapshot for the CSR draft pipeline.

Captures the full responder output (composed message, draft text, panel
content_blocks, matched document chips, execution_run summary) per query,
so that future migration phases (llm_records contract introduction,
draft_llm prompt cuts) can be diffed against a stable pre-refactor baseline.

This is NOT pytest (filename does not match ``test_*.py``). Run manually:

    python tests/snapshot_csr_draft_baseline.py
    python tests/snapshot_csr_draft_baseline.py --out tests/fixtures/csr_draft_custom.json
    python tests/snapshot_csr_draft_baseline.py --note "pre-llm_records baseline"
    python tests/snapshot_csr_draft_baseline.py --filter cart  # only CAR-T queries

Prerequisites
-------------
- SSM tunnel to RDS up (port 5433 default)
- LLM API credentials in environment (.env: ANTHROPIC_API_KEY etc.)
- AWS credentials (~/.aws/credentials or env) for presigned URL minting

Output is a JSON archive under tests/fixtures/. Diff two snapshots (e.g.
before vs after Phase 1 prompt cut) to see how draft text + panel content
shifted for the same query set.

Mirror of ``tests/snapshot_rag_baseline.py`` style.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _preflight() -> None:
    """Fail-fast checks for the runtime env. Bail BEFORE running 18 queries
    if a required dep is missing — saves 5-10 min when the env is wrong.

    Issues seen historically:
      * Running from base anaconda (no boto3) → presigned URL mint fails
        silently per-query, document chip data is wrong, snapshot looks
        "successful" but is contaminated.
      * SSM tunnel down → 16/18 queries fail with PG connection refused.
    """
    missing: list[str] = []
    try:
        import boto3  # noqa: F401
    except ImportError:
        missing.append(
            "boto3 not installed in this Python env. Presigned URL minting "
            "for document chips will fail and the snapshot will be polluted. "
            "Activate the email_agent conda env (or pip install boto3) and re-run."
        )
    try:
        import psycopg  # noqa: F401
    except ImportError:
        missing.append("psycopg not installed in this Python env.")
    if missing:
        print("[preflight FAIL]", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        sys.exit(2)


_preflight()


from src.api_models import AgentRequest
from src.app.service import run_email_agent


DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


# Query corpus covering the migration surfaces.
# Tuple: (category, query, note)
CORPUS: list[tuple[str, str, str]] = [
    # --- catalog: CAR-T (Phase 1 target) ---
    ("cart",        "tell me about PM-CAR1000",
                    "general info ask — fires both flags, mixed demand"),
    ("cart",        "send me PM-CAR1042 flyer please",
                    "explicit documentation request — pure technical"),
    ("cart",        "what's PM-CAR1009 used for?",
                    "general info, narrower 'used for' framing"),
    ("cart_narrow", "what's the cell number for PM-CAR1042?",
                    "narrow field ask — should NOT surface flyer"),
    ("cart_narrow", "do you have PM-CAR1000 in stock?",
                    "pure availability — should NOT surface flyer"),

    # --- catalog: mRNA-LNP (Phase 1 target) ---
    ("lnp",         "info on PM-LNP-0023",
                    "general info — dedup smoke test (was returning siblings)"),
    ("lnp",         "Could you send me the spec sheet for PM-LNP-0050?",
                    "documentation request"),
    ("lnp_narrow",  "what's PM-LNP-0010 encoding?",
                    "narrow field — should NOT surface flyer"),

    # --- catalog: Antibody (Phase 1 target — no product flyer column) ---
    ("antibody",    "tell me about catalog 10007",
                    "general info — antibody, no product flyer exists"),
    ("antibody",    "ELISA dilution for antibody 20338",
                    "narrow field — wb_dilution / elisa_dilution rendering"),

    # --- multi-SKU comparison ---
    ("multi",       "compare PM-CAR1000 and PM-CAR1042",
                    "two product objects — multi-intent or multi-object?"),

    # --- service-level (Phase 3 target) ---
    ("service",     "tell me about your custom CAR-T development service",
                    "service inquiry — primary_service_document path"),
    ("service",     "what's involved in mammalian protein expression?",
                    "service workflow — needs_protocol"),

    # --- pricing (Phase 3 target) ---
    ("pricing",     "how much does PM-CAR1000 cost?",
                    "pure price ask — should NOT surface flyer"),
    ("pricing",     "quote for 100 units of PM-LNP-0010",
                    "quantity-based pricing"),

    # --- orphan / edge cases ---
    ("orphan",      "info on PM-CAR1046",
                    "S3 has flyer but DB has no SKU — should return 0 match"),

    # --- conversational (no tools fire) ---
    ("chat",        "hi",
                    "greeting — no tools, just acknowledgement"),
    ("chat",        "thanks, that's all",
                    "closing — no execution"),
]


def _git_info() -> dict[str, Any]:
    def _run(args: list[str]) -> str:
        try:
            return subprocess.check_output(
                args, cwd=PROJECT_ROOT, stderr=subprocess.DEVNULL,
            ).decode("utf-8").strip()
        except Exception:
            return ""
    return {
        "sha": _run(["git", "rev-parse", "--short", "HEAD"]),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(_run(["git", "status", "--porcelain"])),
    }


def _summarize_executed_call(call: dict[str, Any]) -> dict[str, Any]:
    """Compact one ExecutedToolCall dict for snapshot diff readability.

    Keeps tool_name / role / status / primary_records count + identity-key
    list. Drops verbose request/result bodies (those are diffable via
    structured_facts / records counts which catch contract breaks)."""
    result = call.get("result") or {}
    primary = result.get("primary_records") or []
    return {
        "tool_name": call.get("tool_name"),
        "role": call.get("role"),
        "status": call.get("status"),
        "primary_records_count": len(primary),
        "primary_records_keys": [
            # Heuristic: pick a stable identifier per record so diffs catch
            # "different SKU returned" not just "count differs".
            _record_identity(call.get("tool_name"), r) for r in primary[:10]
        ],
        "structured_facts_keys": sorted((result.get("structured_facts") or {}).keys()),
        "snippets_count": len(result.get("unstructured_snippets") or []),
        "artifacts_count": len(result.get("artifacts") or []),
        "error": call.get("error", ""),
    }


def _record_identity(tool_name: str, record: dict[str, Any]) -> str:
    """Mirror dedup_keys._DEDUP_KEY for snapshot diff legibility."""
    if not isinstance(record, dict):
        return ""
    if tool_name == "document_lookup_tool":
        return (record.get("storage_url") or "").rsplit("/", 1)[-1]
    if tool_name == "catalog_lookup_tool":
        return record.get("catalog_no") or record.get("id") or ""
    if tool_name == "pricing_lookup_tool":
        return "::".join(filter(None, [
            str(record.get("catalog_no") or ""),
            str(record.get("plan_name") or ""),
            str(record.get("phase_name") or ""),
        ]))
    return str(record.get("id") or record.get("doc_number") or record.get("thread_key") or "")


def _summarize_content_block(block: dict[str, Any]) -> dict[str, Any]:
    """Compact a content_block for diff. Body is kept (it's the rendered text)
    but data payload is summarized (record counts / titles)."""
    data = block.get("data") or {}
    summary: dict[str, Any] = {
        "kind": block.get("kind") or block.get("block_type"),
        "title": block.get("title"),
        "body": block.get("body", ""),
    }
    # Mention sizes of common payload arrays for content drift catch.
    for arr_key in ("records", "matches", "files", "threads", "notes"):
        arr = data.get(arr_key)
        if isinstance(arr, list):
            summary[f"data_{arr_key}_count"] = len(arr)
    return summary


def _run_one(category: str, query: str, note: str) -> dict[str, Any]:
    request = AgentRequest(user_query=query, locale="en", start_new_conversation=True)
    try:
        response = run_email_agent(request)
    except Exception as exc:
        return {
            "category": category,
            "query": query,
            "note": note,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }

    payload = response.model_dump(mode="json")

    executed_calls = (payload.get("execution_run") or {}).get("executed_calls") or []
    content_blocks = payload.get("response_content_blocks") or []
    assistant = payload.get("assistant_message") or {}

    return {
        "category": category,
        "query": query,
        "note": note,
        "asked_focus": payload.get("answer_focus", ""),
        "response_path": payload.get("response_path", ""),
        "response_topic": payload.get("response_topic", ""),
        "response_content_summary": payload.get("response_content_summary", ""),
        # The full composed message (draft + sections) — the thing CSR reads.
        "final_message": (payload.get("final_response") or {}).get("message", ""),
        # The draft text alone (without panel sections).
        "assistant_content": assistant.get("content", ""),
        # Chip metadata (separately rendered as clickable downloads).
        "assistant_documents": assistant.get("metadata", {}).get("documents", []),
        # Per-tool call summary — catches "ran wrong tool" / "returned wrong SKU".
        "executed_calls": [_summarize_executed_call(c) for c in executed_calls],
        # Per-panel summary — catches "panel disappeared" / "rendering changed".
        "content_blocks": [_summarize_content_block(b) for b in content_blocks],
    }


def _print_summary(rows: list[dict[str, Any]]) -> None:
    print(
        f"\n{'idx':>3} | {'category':<14} | {'tools':>5} | {'blocks':>6} | "
        f"{'chips':>5} | {'draft_len':>9} | query"
    )
    print("-" * 130)
    for idx, row in enumerate(rows, start=1):
        if row.get("error"):
            print(f"{idx:>3} | {row['category']:<14} | ERROR: {row['error'][:80]}")
            continue
        n_tools = len(row.get("executed_calls") or [])
        n_blocks = len(row.get("content_blocks") or [])
        n_chips = len(row.get("assistant_documents") or [])
        draft_len = len(row.get("assistant_content") or "")
        q = row["query"][:60]
        print(
            f"{idx:>3} | {row['category']:<14} | "
            f"{n_tools:>5} | {n_blocks:>6} | {n_chips:>5} | {draft_len:>9} | {q}"
        )


def run_snapshot(out_path: Path, note: str, category_filter: str = "") -> Path:
    if category_filter:
        corpus = [r for r in CORPUS if category_filter in r[0]]
    else:
        corpus = CORPUS

    total = len(corpus)
    if total == 0:
        print(f"[warn] no queries match filter '{category_filter}'.", file=sys.stderr)
        sys.exit(2)

    rows: list[dict[str, Any]] = []
    for idx, (category, query, query_note) in enumerate(corpus, start=1):
        print(f"[{idx}/{total}] ({category}) {query[:70]}", file=sys.stderr)
        rows.append(_run_one(category, query, query_note))

    snapshot = {
        "snapshot_metadata": {
            "taken_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "git": _git_info(),
            "query_count": total,
            "category_filter": category_filter or "(all)",
            "note": note,
            "corpus_source": __file__ + "::CORPUS",
        },
        "queries": rows,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    _print_summary(rows)
    n_err = sum(1 for r in rows if r.get("error"))
    print(f"\nSnapshot written: {out_path}", file=sys.stderr)
    print(f"Queries: {total}  |  errors: {n_err}", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    # Include HHMM so two runs on the same day don't silently overwrite each
    # other — captured the hard way during the Phase 1 step 6 cut/diff cycle.
    default_name = f"csr_draft_baseline_{dt.datetime.now():%Y%m%d_%H%M}.json"
    parser.add_argument(
        "--out",
        default=str(DEFAULT_FIXTURES_DIR / default_name),
        help=f"Output path (default: tests/fixtures/csr_draft_baseline_<YYYYMMDD>_<HHMM>.json)",
    )
    parser.add_argument(
        "--note",
        default="Phase 0 baseline (pre-llm_records contract).",
        help="Free-form note embedded in snapshot metadata.",
    )
    parser.add_argument(
        "--filter",
        default="",
        help="Substring filter on category (e.g. 'cart' / 'lnp' / 'pricing').",
    )
    args = parser.parse_args()
    run_snapshot(Path(args.out), args.note, args.filter)
