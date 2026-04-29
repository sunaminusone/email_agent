"""Ablate parser_semantic_intent pass-through (2026-04-24).

Dry-run: no main code changes. Monkey-patches `detect_intent_bucket` to
recognize parser intents (pricing_question, timeline_question) and adds a
"pricing" bucket to `_SECTION_TYPE_BOOSTS`. Then injects hypothesized parser
intent into `scope_context["context"]["semantic_intent"]` for targeted GT rows.

Compares baseline vs patched on all GT=yes rows and highlights idx=27 (the
main target — current miss: workflow_overview instead of pricing_overview).

Usage:
    python tests/ablate_parser_intent.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag import query_scope, retriever, service  # noqa: E402
from tests.observe_rag_accuracy import GT_LABELS  # noqa: E402
from tests.observe_rag_confidence import CORPUS  # noqa: E402


# Hypothesized parser intent for idxs where parser should plausibly produce
# a non-"technical_question" intent. Other idxs run without injection.
PARSER_INTENT: dict[int, str] = {
    27: "pricing_question",   # "quote for polyclonal antibody production"
    9:  "timeline_question",  # "What's the timeline for this service?"
}


_original_detect = query_scope.detect_intent_bucket
_current_parser_intent: dict[str, str] = {"value": ""}


def _patched_detect(query: str) -> str:
    pi = _current_parser_intent.get("value", "")
    if pi == "pricing_question":
        return "pricing"
    if pi == "timeline_question":
        return "service_plan"
    return _original_detect(query)


def _apply_patches() -> None:
    service.detect_intent_bucket = _patched_detect  # service.py imported at top
    query_scope.detect_intent_bucket = _patched_detect
    retriever._SECTION_TYPE_BOOSTS["pricing"] = {
        "pricing_overview": 0.08,
        "add_on_service_pricing": 0.06,
    }


def _remove_patches() -> None:
    service.detect_intent_bucket = _original_detect
    query_scope.detect_intent_bucket = _original_detect
    retriever._SECTION_TYPE_BOOSTS.pop("pricing", None)


def _run_one(idx: int, inject_intent: str = "") -> dict[str, Any]:
    category, query, ctx = CORPUS[idx - 1]
    _current_parser_intent["value"] = inject_intent

    call_kwargs = dict(ctx)
    if inject_intent:
        scope_ctx = dict(call_kwargs.get("scope_context") or {})
        inner = dict(scope_ctx.get("context") or {})
        inner["semantic_intent"] = inject_intent
        scope_ctx["context"] = inner
        call_kwargs["scope_context"] = scope_ctx

    result = service.retrieve_technical_knowledge(query=query, **call_kwargs)
    matches = result.get("matches", []) or []
    confidence = result.get("confidence", {}) or {}
    debug = result.get("retrieval_debug", {}) or {}

    top_file = Path(str(matches[0].get("source_path", ""))).name if matches else ""
    top_section = str(matches[0].get("section_type", "")) if matches else ""
    top_final = round(float(confidence.get("top_final_score", 0.0)), 3)
    intent_bucket = debug.get("intent_bucket", "")

    top5 = [
        {
            "section": str(m.get("section_type", "")),
            "file": Path(str(m.get("source_path", ""))).name,
            "final": round(float(m.get("final_score") or 0.0), 3),
            "raw": round(float(m.get("raw_score") or 0.0), 3),
            "breakdown": m.get("score_breakdown") or {},
        }
        for m in matches[:5]
    ]

    _current_parser_intent["value"] = ""
    return {
        "idx": idx,
        "query": query,
        "top_file": top_file,
        "top_section": top_section,
        "top_final": top_final,
        "intent_bucket": intent_bucket,
        "top5": top5,
    }


def _format_row(row: dict[str, Any], gt: dict[str, Any]) -> str:
    exp_file = gt.get("expected_file") or ""
    exp_section = gt.get("expected_section") or ""
    hit_file = row["top_file"] == exp_file if exp_file else None
    hit_section = row["top_section"] == exp_section if exp_section else None
    fm = "✓" if hit_file else ("✗" if hit_file is False else "-")
    sm = "✓" if hit_section else ("✗" if hit_section is False else "-")
    return (
        f"  file={fm} section={sm} bucket={row['intent_bucket']:<16} "
        f"top_final={row['top_final']:>6}  "
        f"got: {row['top_file'][:50]} :: {row['top_section']}"
    )


def main() -> None:
    target_idxs = sorted(i for i, gt in GT_LABELS.items() if gt.get("gt_in_kb") == "yes")

    # === Baseline ===
    print("=" * 78)
    print("BASELINE (no patches)")
    print("=" * 78)
    baseline: dict[int, dict[str, Any]] = {}
    for idx in target_idxs:
        row = _run_one(idx, inject_intent="")
        baseline[idx] = row
        gt = GT_LABELS[idx]
        mark = " ⭐" if idx in PARSER_INTENT else ""
        print(f"\n[{idx}]{mark} {row['query'][:60]}")
        print(f"  expected: {(gt.get('expected_file') or '')[:50]} :: {gt.get('expected_section') or ''}")
        print(_format_row(row, gt))

    # === Patched ===
    _apply_patches()
    print("\n" + "=" * 78)
    print("PATCHED (parser_intent injected for idxs in PARSER_INTENT + pricing bucket added)")
    print("=" * 78)
    patched: dict[int, dict[str, Any]] = {}
    for idx in target_idxs:
        inject = PARSER_INTENT.get(idx, "")
        row = _run_one(idx, inject_intent=inject)
        patched[idx] = row
        gt = GT_LABELS[idx]
        mark = f" ⭐ inject={inject}" if inject else ""
        print(f"\n[{idx}]{mark} {row['query'][:60]}")
        print(f"  expected: {(gt.get('expected_file') or '')[:50]} :: {gt.get('expected_section') or ''}")
        print(_format_row(row, gt))
    _remove_patches()

    # === Diff ===
    print("\n" + "=" * 78)
    print("DIFF (baseline → patched)")
    print("=" * 78)
    for idx in target_idxs:
        b = baseline[idx]
        p = patched[idx]
        gt = GT_LABELS[idx]
        b_hit_file = b["top_file"] == gt.get("expected_file")
        p_hit_file = p["top_file"] == gt.get("expected_file")
        b_hit_sec = b["top_section"] == gt.get("expected_section")
        p_hit_sec = p["top_section"] == gt.get("expected_section")
        changed = (b["top_file"] != p["top_file"]) or (b["top_section"] != p["top_section"])
        status = ""
        if b_hit_sec and not p_hit_sec:
            status = "⚠ SECTION REGRESSION"
        elif not b_hit_sec and p_hit_sec:
            status = "✅ SECTION FIXED"
        elif b_hit_file and not p_hit_file:
            status = "⚠ FILE REGRESSION"
        elif not b_hit_file and p_hit_file:
            status = "✅ FILE FIXED"
        elif changed:
            status = "~ changed (no hit change)"
        else:
            status = "= unchanged"
        print(f"\n[{idx}] {status}")
        print(f"  baseline: {b['top_section']:<24} ({b['top_file'][:40]})  bucket={b['intent_bucket']}")
        print(f"  patched : {p['top_section']:<24} ({p['top_file'][:40]})  bucket={p['intent_bucket']}")

    # === Query-rewrite hypothesis for idx=27 ===
    print("\n" + "=" * 78)
    print("QUERY-REWRITE TEST: idx=27 with 'pricing' keywords added to query")
    print("=" * 78)
    rewrite_variants = [
        "I'd like to get a quote for a polyclonal antibody production",  # original
        "pricing for polyclonal antibody production",
        "cost and price quote for polyclonal antibody production",
        "how much does polyclonal antibody production cost",
    ]
    _, _, ctx27 = CORPUS[26]
    for variant in rewrite_variants:
        result = service.retrieve_technical_knowledge(query=variant, **ctx27)
        matches = result.get("matches", []) or []
        if matches:
            top = matches[0]
            top_file = Path(str(top.get("source_path", ""))).name
            top_section = str(top.get("section_type", ""))
            top_final = round(float(top.get("final_score") or 0.0), 3)
        else:
            top_file = top_section = ""
            top_final = 0.0
        mark = "✓" if top_section == "pricing_overview" else "✗"
        print(f"  {mark} query: {variant[:58]}")
        print(f"     → top: {top_section:<24} final={top_final}  ({top_file[:40]})")

    # Deep dive: idx=27 top-5 breakdown
    print("\n" + "=" * 78)
    print("DEEP DIVE: idx=27 top-5 sections (baseline vs patched)")
    print("=" * 78)
    for label, row in [("BASELINE", baseline[27]), ("PATCHED", patched[27])]:
        print(f"\n[{label}] bucket={row['intent_bucket']}")
        for rank, m in enumerate(row["top5"], 1):
            bd = m["breakdown"]
            print(f"  {rank}. {m['section']:<22} final={m['final']:>6}  raw={m['raw']:>6}")
            parts = [f"    {k}={v}" for k, v in bd.items() if v not in (0, 0.0, "", None)]
            for p in parts:
                print(p)

    # Rollup
    print("\n" + "=" * 78)
    print("ROLLUP (GT=yes n={})".format(len(target_idxs)))
    print("=" * 78)
    b_file = sum(1 for i in target_idxs if baseline[i]["top_file"] == GT_LABELS[i].get("expected_file"))
    p_file = sum(1 for i in target_idxs if patched[i]["top_file"] == GT_LABELS[i].get("expected_file"))
    b_sec = sum(1 for i in target_idxs if baseline[i]["top_section"] == GT_LABELS[i].get("expected_section"))
    p_sec = sum(1 for i in target_idxs if patched[i]["top_section"] == GT_LABELS[i].get("expected_section"))
    n = len(target_idxs)
    print(f"  top-1 file   : baseline {b_file}/{n} → patched {p_file}/{n}  (Δ={p_file - b_file:+d})")
    print(f"  top-1 section: baseline {b_sec}/{n} → patched {p_sec}/{n}  (Δ={p_sec - b_sec:+d})")


if __name__ == "__main__":
    main()
