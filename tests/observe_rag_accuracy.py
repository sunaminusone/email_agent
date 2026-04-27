"""Measure RAG retrieval accuracy against ground-truth labels (2026-04-24).

Axis-3 measurement: for a hand-labeled subset of the v1 CORPUS, compare the
retriever's top-1 / top-5 chunk against the expected file+section. Separates
three evaluation buckets:

    yes      — KB has the answer; measure file_hit / section_hit / top5_in
    partial  — KB partially covers; measure file_hit only
    no       — KB gap or off-domain; measure "graceful" (top_final < 0)

Un-labeled CORPUS rows still get retrieved and written, but with blank
hit columns — useful for seeing the full distribution.

Usage:
    python tests/observe_rag_accuracy.py
    python tests/observe_rag_accuracy.py --csv outputs/observe_rag_accuracy.csv
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

from src.ingestion.parser_adapter import (  # noqa: E402
    adapt_parsed_result_to_parser_signals,
    invoke_parser,
)
from src.rag.service import retrieve_technical_knowledge  # noqa: E402
from tests.observe_rag_confidence import CORPUS  # noqa: E402


# Ground truth keyed by 1-based CORPUS idx.
# gt_in_kb: "yes" | "partial" | "no"
# expected_file: filename (no path), or None
# expected_section: section_type string, or None (partial/no)
GT_LABELS: dict[int, dict[str, Any]] = {
    2: {
        "gt_in_kb": "yes",
        "expected_file": "promab_antibody_production_rag_ready_v1.txt",
        "expected_section": "workflow_overview",
    },
    3: {
        "gt_in_kb": "yes",
        "expected_file": "promab_mrna_lnp_gene_delivery_rag_ready.txt",
        "expected_section": "model_support",
    },
    6: {
        "gt_in_kb": "yes",
        "expected_file": "promab_custom_car_t_cell_development_rag_ready_v1.txt",
        "expected_section": "workflow_overview",
    },
    9: {
        "gt_in_kb": "yes",
        "expected_file": "promab_custom_car_t_cell_development_rag_ready_v1.txt",
        "expected_section": "timeline_overview",
    },
    22: {
        "gt_in_kb": "yes",
        "expected_file": "promab_custom_car_t_cell_development_rag_ready_v1.txt",
        "expected_section": "model_support",
    },
    23: {
        "gt_in_kb": "yes",
        "expected_file": "promab_hybridoma_sequencing_rag_ready_v1.txt",
        "expected_section": "service_overview",
    },
    27: {
        "gt_in_kb": "yes",
        "expected_file": "promab_rabbit_polyclonal_antibodies_rag_ready_v1.txt",
        "expected_section": "pricing_overview",
    },
    35: {
        "gt_in_kb": "yes",
        "expected_file": "promab_macrophage_polarization_assay_rag_ready_v1.txt",
        "expected_section": "application_use_case",
    },
    31: {
        "gt_in_kb": "no",
        "expected_file": None,
        "expected_section": None,
        "note": "KB gap: no dosage-form coverage (aqueous/lyophilized)",
    },
    36: {
        "gt_in_kb": "no",
        "expected_file": None,
        "expected_section": None,
        "note": "KB gap: shRNA/siRNA cargo not covered",
    },
    37: {
        "gt_in_kb": "partial",
        "expected_file": "promab_rabbit_polyclonal_antibodies_rag_ready_v1.txt",
        "expected_section": None,
        "note": "General pAb service; bacterium-as-immunogen detail not explicit",
    },
    28: {
        "gt_in_kb": "partial",
        "expected_file": "promab_custom_car_t_cell_development_rag_ready_v1.txt",
        "expected_section": None,
        "note": "Xenograft as dev-phase, not post-dev CRO service",
    },
    10: {
        "gt_in_kb": "no",
        "expected_file": None,
        "expected_section": None,
        "note": "Off-domain: customer service (phone number)",
    },
    14: {
        "gt_in_kb": "no",
        "expected_file": None,
        "expected_section": None,
        "note": "Off-domain: weather",
    },
}


def _run(with_parser: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(CORPUS)
    for idx, (category, query, ctx) in enumerate(CORPUS, start=1):
        print(f"[{idx}/{total}] ({category}) {query[:60]}", file=sys.stderr)

        # A' mode: parse query first, plumb semantic_intent into scope_context
        # so retrieve_technical_knowledge consumes the real parser bucket
        # rather than the keyword fallback. Per-row try/except so a single
        # parser timeout doesn't abort the whole sweep — failed rows fall
        # back to empty intent (keyword fallback path) and record the error.
        parsed_intent = ""
        parser_error = ""
        call_ctx = dict(ctx)
        if with_parser:
            try:
                payload = invoke_parser(user_query=query)
                signals = adapt_parsed_result_to_parser_signals(payload, source_query=query)
                parsed_intent = (signals.context.semantic_intent or "").strip()
            except Exception as exc:
                parser_error = f"{type(exc).__name__}: {exc}"
                print(f"  parser error: {parser_error}", file=sys.stderr)
            scope_override = dict(call_ctx.get("scope_context") or {})
            scope_override.setdefault("context", {})
            scope_override["context"] = {**scope_override["context"], "semantic_intent": parsed_intent}
            call_ctx["scope_context"] = scope_override

        result = retrieve_technical_knowledge(query=query, **call_ctx)
        confidence = result.get("confidence", {}) or {}
        debug = result.get("retrieval_debug", {}) or {}
        matches = result.get("matches", []) or []

        top_files = [Path(str(m.get("source_path", ""))).name for m in matches[:5]]
        top_sections = [str(m.get("section_type", "")) for m in matches[:5]]
        top_file = top_files[0] if top_files else ""
        top_section = top_sections[0] if top_sections else ""

        gt = GT_LABELS.get(idx)
        gt_in_kb = gt["gt_in_kb"] if gt else ""
        expected_file = gt.get("expected_file") if gt else None
        expected_section = gt.get("expected_section") if gt else None

        file_hit: str = ""
        section_hit: str = ""
        file_in_top5: str = ""
        graceful: str = ""

        if gt_in_kb == "yes":
            file_hit = "Y" if top_file == expected_file else "N"
            section_hit = "Y" if top_section == expected_section else "N"
            file_in_top5 = "Y" if expected_file in top_files else "N"
        elif gt_in_kb == "partial":
            file_hit = "Y" if top_file == expected_file else "N"
            file_in_top5 = "Y" if expected_file in top_files else "N"
        elif gt_in_kb == "no":
            top_final_val = float(confidence.get("top_final_score", 0.0))
            graceful = "Y" if top_final_val < 0 else "N"

        rows.append({
            "idx": idx,
            "category": category,
            "query": query[:70],
            "gt_in_kb": gt_in_kb,
            "expected_file": expected_file or "",
            "expected_section": expected_section or "",
            "top_file": top_file,
            "top_section": top_section,
            "top_final": round(float(confidence.get("top_final_score", 0.0)), 3),
            "intent_bucket": debug.get("intent_bucket", ""),
            "parsed_semantic_intent": parsed_intent,
            "parser_error": parser_error,
            "file_hit": file_hit,
            "section_hit": section_hit,
            "file_in_top5": file_in_top5,
            "graceful": graceful,
            "top5_files": " | ".join(f[:40] for f in top_files),
        })
    return rows


def _rollup(rows: list[dict[str, Any]]) -> None:
    yes_rows = [r for r in rows if r["gt_in_kb"] == "yes"]
    partial_rows = [r for r in rows if r["gt_in_kb"] == "partial"]
    no_rows = [r for r in rows if r["gt_in_kb"] == "no"]

    print("\n=== AXIS-3 ACCURACY ROLLUP ===")

    if yes_rows:
        n = len(yes_rows)
        file_hit_n = sum(1 for r in yes_rows if r["file_hit"] == "Y")
        section_hit_n = sum(1 for r in yes_rows if r["section_hit"] == "Y")
        top5_in_n = sum(1 for r in yes_rows if r["file_in_top5"] == "Y")
        print(f"\n[GT=yes]  n={n}")
        print(f"  top-1 file    : {file_hit_n}/{n}  ({file_hit_n/n*100:.0f}%)")
        print(f"  top-1 section : {section_hit_n}/{n}  ({section_hit_n/n*100:.0f}%)")
        print(f"  top-5 file    : {top5_in_n}/{n}  ({top5_in_n/n*100:.0f}%)")

    if partial_rows:
        n = len(partial_rows)
        file_hit_n = sum(1 for r in partial_rows if r["file_hit"] == "Y")
        top5_in_n = sum(1 for r in partial_rows if r["file_in_top5"] == "Y")
        print(f"\n[GT=partial]  n={n}  (only file_hit checked)")
        print(f"  top-1 file    : {file_hit_n}/{n}")
        print(f"  top-5 file    : {top5_in_n}/{n}")

    if no_rows:
        n = len(no_rows)
        graceful_n = sum(1 for r in no_rows if r["graceful"] == "Y")
        print(f"\n[GT=no]  n={n}  (graceful = top_final < 0)")
        print(f"  graceful      : {graceful_n}/{n}")
        print(f"  hallucinate risk (top_final >= 0): {n - graceful_n}/{n}")
        for r in no_rows:
            if r["graceful"] == "N":
                print(f"    ⚠  idx={r['idx']}  top_final={r['top_final']}  top_file={r['top_file']}  query={r['query'][:50]}")

    print("\n=== MISSES (GT=yes file_hit=N) ===")
    misses = [r for r in yes_rows if r["file_hit"] == "N"]
    if not misses:
        print("(none)")
    for r in misses:
        print(
            f"  idx={r['idx']}  query={r['query'][:45]}\n"
            f"    expected: {r['expected_file']} :: {r['expected_section']}\n"
            f"    got     : {r['top_file']} :: {r['top_section']}  (top_final={r['top_final']})"
        )

    print("\n=== SECTION-ONLY MISSES (GT=yes file_hit=Y section_hit=N) ===")
    sec_misses = [r for r in yes_rows if r["file_hit"] == "Y" and r["section_hit"] == "N"]
    if not sec_misses:
        print("(none)")
    for r in sec_misses:
        print(
            f"  idx={r['idx']}  query={r['query'][:45]}\n"
            f"    expected section: {r['expected_section']}\n"
            f"    got section     : {r['top_section']}  (top_final={r['top_final']})"
        )


def _export_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nexported {path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=str, default="outputs/observe_rag_accuracy.csv")
    parser.add_argument(
        "--with-parser",
        action="store_true",
        help="Run parser on each query and inject semantic_intent into RAG scope_context (A' mode).",
    )
    args = parser.parse_args()

    rows = _run(with_parser=args.with_parser)
    _rollup(rows)
    if args.csv:
        _export_csv(rows, PROJECT_ROOT / args.csv)


if __name__ == "__main__":
    main()
