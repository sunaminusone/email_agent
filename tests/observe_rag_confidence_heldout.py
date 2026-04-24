"""Held-out e2e observation: overfitting check for 7a parser prompt changes.

Mirrors `observe_rag_confidence_e2e.py` but sweeps the fixture in
`tests/fixtures/rag_heldout_corpus_v2.py` instead of `CORPUS` Section VI.
The v2 corpus was not seen during 7a prompt iteration, so running this
yields an unbiased measurement of whether 7a generalizes.

Usage:
    python tests/observe_rag_confidence_heldout.py
    python tests/observe_rag_confidence_heldout.py --csv out.csv
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

from src.ingestion.pipeline import build_ingestion_bundle  # noqa: E402
from src.objects.registries.service_registry import KNOWN_BUSINESS_LINES  # noqa: E402
from src.rag.service import retrieve_technical_knowledge  # noqa: E402
from tests.fixtures.rag_heldout_corpus_v2 import CORPUS_HELDOUT_V2  # noqa: E402


def _validate_corpus(corpus: list[tuple[str, str, dict[str, Any]]]) -> None:
    allowed = KNOWN_BUSINESS_LINES | {""}
    for _, query, ctx in corpus:
        hint = str(ctx.get("business_line_hint", "") or "").strip()
        if hint not in allowed:
            raise ValueError(
                f"business_line_hint={hint!r} is not in KNOWN_BUSINESS_LINES "
                f"for query {query!r}. Allowed: {sorted(KNOWN_BUSINESS_LINES)}"
            )


def run_observation(csv_path: str | None = None) -> None:
    _validate_corpus(CORPUS_HELDOUT_V2)
    rows: list[dict[str, Any]] = []
    total = len(CORPUS_HELDOUT_V2)
    for idx, (category, query, ctx) in enumerate(CORPUS_HELDOUT_V2, start=1):
        print(f"[{idx}/{total}] ({category}) {query[:70]}", file=sys.stderr)

        bundle = build_ingestion_bundle(
            thread_id=f"heldout-v2-{idx}",
            user_query=query,
            conversation_history=None,
            attachments=None,
            prior_state=None,
            stateful_anchors=None,
            has_recent_objects=False,
        )
        normalized = bundle.turn_core.normalized_query
        ps = bundle.turn_signals.parser_signals

        parser_kw = list(ps.retrieval_hints.keywords) if ps.retrieval_hints and ps.retrieval_hints.keywords else []
        parser_xq = list(ps.retrieval_hints.expanded_queries) if ps.retrieval_hints and ps.retrieval_hints.expanded_queries else []

        merged_hints = {
            "expanded_queries": parser_xq,
            "keywords": parser_kw,
        }
        usage = (ps.constraints.usage_context if ps.constraints else None) or ""
        merged_context = {
            "experiment_type": "",
            "usage_context": usage,
            "pain_point": "",
            "regulatory_or_compliance_note": "",
            "keywords": parser_kw,
        }

        result = retrieve_technical_knowledge(
            query=normalized,
            business_line_hint=ctx.get("business_line_hint", ""),
            active_service_name="",
            active_product_name="",
            product_names=[],
            service_names=[],
            retrieval_hints=merged_hints,
            retrieval_context=merged_context,
        )
        confidence = result.get("confidence", {}) or {}
        debug = result.get("retrieval_debug", {}) or {}
        matches = result.get("matches", []) or []
        top_section = str(matches[0].get("section_type", "")) if matches else ""
        rows.append({
            "idx": idx,
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
