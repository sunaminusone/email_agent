"""Phase 0 baseline snapshot for the RAG technical-inquiry pipeline.

Captures the full retrieval output (top-10 chunk_keys + score_breakdown +
retrieval_debug + confidence) per query, so that future changes — most
immediately the hybrid-search (dense + BM25) rollout — can be compared
against a stable dense-only baseline.

This is NOT pytest (filename does not match `test_*.py`). Run manually:
    python tests/snapshot_rag_baseline.py
    python tests/snapshot_rag_baseline.py --out tests/fixtures/rag_baseline_custom.json
    python tests/snapshot_rag_baseline.py --note "pre-hybrid baseline"

Output is a JSON archive under tests/fixtures/. Diff two snapshots (e.g.
before vs after hybrid search) to see which chunks moved in/out of top-k
and how score_breakdown shifted.
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

from src.rag.service import retrieve_technical_knowledge
from tests.observe_rag_confidence import CORPUS

TOP_K = 10
DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


def _git_info() -> dict[str, str]:
    def _run(args: list[str]) -> str:
        try:
            return subprocess.check_output(
                args, cwd=PROJECT_ROOT, stderr=subprocess.DEVNULL
            ).decode("utf-8").strip()
        except Exception:
            return ""
    return {
        "sha": _run(["git", "rev-parse", "--short", "HEAD"]),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(_run(["git", "status", "--porcelain"])),
    }


def _extract_match(item: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "chunk_key": item.get("chunk_key", ""),
        "final_score": item.get("final_score"),
        "score": item.get("score"),
        "raw_score": item.get("raw_score"),
        "priority_tier": item.get("priority_tier"),
        "score_breakdown": item.get("score_breakdown") or {},
        "query_variant": item.get("query_variant", ""),
        "section_type": item.get("section_type", ""),
        "structural_tag": item.get("structural_tag", ""),
        "chunk_label": item.get("chunk_label", ""),
        "source_path": item.get("source_path", ""),
        "file_name": item.get("file_name", ""),
        "business_line": item.get("business_line", ""),
    }


def _run_one(category: str, query: str, ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        result = retrieve_technical_knowledge(query=query, top_k=TOP_K, **ctx)
    except Exception as exc:
        return {
            "category": category,
            "query": query,
            "context": ctx,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }

    matches = result.get("matches") or []
    return {
        "category": category,
        "query": query,
        "context": ctx,
        "confidence": result.get("confidence") or {},
        "retrieval_debug": result.get("retrieval_debug") or {},
        "retrieval_mode": result.get("retrieval_mode", ""),
        "query_variants": result.get("query_variants") or [],
        "documents_found": result.get("documents_found", 0),
        "top_matches": [_extract_match(m, rank=i + 1) for i, m in enumerate(matches)],
    }


def _print_summary(rows: list[dict[str, Any]]) -> None:
    print(f"\n{'idx':>3} | {'cat':<10} | {'top_final':>9} | {'top_base':>8} | {'margin':>7} | {'n':>3} | {'synth':>5} | query")
    print("-" * 110)
    for idx, row in enumerate(rows, start=1):
        if row.get("error"):
            print(f"{idx:>3} | {row['category']:<10} | ERROR: {row['error'][:70]}")
            continue
        conf = row["confidence"]
        print(
            f"{idx:>3} | {row['category']:<10} | "
            f"{conf.get('top_final_score', 0):>9.3f} | "
            f"{conf.get('top_base_score', 0):>8.3f} | "
            f"{conf.get('top_margin', 0):>7.3f} | "
            f"{conf.get('matches_count', 0):>3} | "
            f"{str(conf.get('top_is_synthesized', False))[:5]:>5} | "
            f"{row['query'][:60]}"
        )


def run_snapshot(out_path: Path, note: str) -> Path:
    total = len(CORPUS)
    rows: list[dict[str, Any]] = []
    for idx, (category, query, ctx) in enumerate(CORPUS, start=1):
        print(f"[{idx}/{total}] ({category}) {query[:70]}", file=sys.stderr)
        rows.append(_run_one(category, query, ctx))

    snapshot = {
        "snapshot_metadata": {
            "taken_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "git": _git_info(),
            "top_k": TOP_K,
            "query_count": total,
            "note": note,
            "corpus_source": "tests/observe_rag_confidence.py::CORPUS",
        },
        "queries": rows,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    _print_summary(rows)
    print(f"\nSnapshot written: {out_path}", file=sys.stderr)
    print(f"Queries: {total}  |  errors: {sum(1 for r in rows if r.get('error'))}", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    default_name = f"rag_baseline_{dt.date.today():%Y%m%d}.json"
    parser.add_argument(
        "--out",
        default=str(DEFAULT_FIXTURES_DIR / default_name),
        help=f"Output path (default: tests/fixtures/{default_name})",
    )
    parser.add_argument(
        "--note",
        default="Phase 0 baseline (dense-only, pre-hybrid-search).",
        help="Free-form note embedded in snapshot metadata.",
    )
    args = parser.parse_args()
    run_snapshot(Path(args.out), args.note)
