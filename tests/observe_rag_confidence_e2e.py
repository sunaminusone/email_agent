"""End-to-end observation: corpus → ingestion → RAG.

Companion to `observe_rag_confidence.py`. The older script feeds raw queries
directly into `retrieve_technical_knowledge`, bypassing `src/ingestion/`. This
script mirrors the production call path in `src/executor/engine.py:183`:

    raw query → build_ingestion_bundle() → turn_core.normalized_query
             + parser_signals.retrieval_hints → retrieve_technical_knowledge

Use this when you want the distribution to reflect real customer experience
rather than RAG subsystem-only performance.

Usage:
    python tests/observe_rag_confidence_e2e.py
    python tests/observe_rag_confidence_e2e.py --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# Allow importing CORPUS from the sibling subsystem observer.
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from observe_rag_confidence import CORPUS, _validate_corpus  # noqa: E402
from src.ingestion.pipeline import build_ingestion_bundle  # noqa: E402
from src.rag.service import retrieve_technical_knowledge  # noqa: E402


def _merge_retrieval_hints(
    ctx_hints: dict[str, Any] | None,
    parser_hints: Any,
) -> dict[str, Any]:
    """Parser hints take precedence; ctx hints fall back when parser leaves a field empty."""
    ctx_hints = ctx_hints or {}
    parser_expanded = list(parser_hints.expanded_queries) if parser_hints and parser_hints.expanded_queries else []
    parser_keywords = list(parser_hints.keywords) if parser_hints and parser_hints.keywords else []
    return {
        "expanded_queries": parser_expanded or list(ctx_hints.get("expanded_queries", []) or []),
        "keywords": parser_keywords or list(ctx_hints.get("keywords", []) or []),
    }


def _merge_retrieval_context(
    ctx_ctx: dict[str, Any] | None,
    parser_constraints: Any,
    parser_context: Any,
    parser_keywords: list[str],
) -> dict[str, Any]:
    ctx_ctx = ctx_ctx or {}
    usage = (
        (parser_constraints.usage_context if parser_constraints else None)
        or ctx_ctx.get("usage_context")
        or ""
    )
    return {
        "experiment_type": ctx_ctx.get("experiment_type", ""),
        "usage_context": usage,
        "pain_point": ctx_ctx.get("pain_point", ""),
        "regulatory_or_compliance_note": ctx_ctx.get("regulatory_or_compliance_note", ""),
        "keywords": parser_keywords or list(ctx_ctx.get("keywords", []) or []),
    }


def run_observation(csv_path: str | None = None) -> None:
    _validate_corpus(CORPUS)
    rows: list[dict[str, Any]] = []
    total = len(CORPUS)
    for idx, (category, query, ctx) in enumerate(CORPUS, start=1):
        print(f"[{idx}/{total}] ({category}) {query[:70]}", file=sys.stderr)

        bundle = build_ingestion_bundle(
            thread_id=f"obs-e2e-{idx}",
            user_query=query,
            conversation_history=None,
            attachments=None,
        )
        normalized = bundle.turn_core.normalized_query
        ps = bundle.turn_signals.parser_signals

        parser_kw = list(ps.retrieval_hints.keywords) if ps.retrieval_hints and ps.retrieval_hints.keywords else []
        parser_xq = list(ps.retrieval_hints.expanded_queries) if ps.retrieval_hints and ps.retrieval_hints.expanded_queries else []

        merged_hints = _merge_retrieval_hints(
            ctx.get("retrieval_hints"),
            ps.retrieval_hints,
        )
        merged_context = _merge_retrieval_context(
            ctx.get("retrieval_context"),
            ps.constraints,
            ps.context,
            parser_kw,
        )

        result = retrieve_technical_knowledge(
            query=normalized,
            business_line_hint=ctx.get("business_line_hint", ""),
            active_service_name=ctx.get("active_service_name", ""),
            active_product_name=ctx.get("active_product_name", ""),
            product_names=ctx.get("product_names", []) or [],
            service_names=ctx.get("service_names", []) or [],
            retrieval_hints=merged_hints,
            retrieval_context=merged_context,
        )
        confidence = result.get("confidence", {}) or {}
        debug = result.get("retrieval_debug", {}) or {}
        matches = result.get("matches", []) or []
        top_section = str(matches[0].get("section_type", "")) if matches else ""
        rows.append({
            "category": category,
            "query": query[:60],
            "intent_bucket": debug.get("intent_bucket", ""),
            "top_final": round(float(confidence.get("top_final_score", 0.0)), 3),
            "top_base": round(float(confidence.get("top_base_score", 0.0)), 3),
            "top_margin": round(float(confidence.get("top_margin", 0.0)), 3),
            "matches": int(confidence.get("matches_count", 0)),
            "synth": bool(confidence.get("top_is_synthesized", False)),
            "top_section": top_section[:24],
            "parser_xq_count": len(parser_xq),
            "parser_kw_count": len(parser_kw),
            "normalized_len": len(normalized),
            "raw_len": len(query),
        })

    _print_table(rows)
    if csv_path:
        _export_csv(rows, csv_path)
        print(f"\nCSV exported: {csv_path}", file=sys.stderr)


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no rows)")
        return
    headers = list(rows[0].keys())
    widths = {h: max(len(h), max(len(str(r[h])) for r in rows)) for h in headers}
    sep = "-+-".join("-" * widths[h] for h in headers)
    line = " | ".join(h.ljust(widths[h]) for h in headers)
    print(line)
    print(sep)
    current_cat = None
    for r in rows:
        if current_cat is not None and r["category"] != current_cat:
            print(sep)
        current_cat = r["category"]
        print(" | ".join(str(r[h]).ljust(widths[h]) for h in headers))


def _export_csv(rows: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", help="Optional path to export results as CSV")
    args = parser.parse_args()
    run_observation(csv_path=args.csv)
