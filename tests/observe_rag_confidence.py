"""Observation script: sweep a query corpus through the real RAG retriever
and tabulate the confidence signals.

This is NOT a pytest test (filename does not match `test_*.py`). Its purpose
is to collect the observed distribution of `top_final_score` / `top_margin`
across representative query categories, so that Phase-2 can pick informed
thresholds for RAG-confidence-driven handoff.

Usage:
    python tests/observe_rag_confidence.py
    python tests/observe_rag_confidence.py --csv out.csv
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

from src.objects.registries.service_registry import KNOWN_BUSINESS_LINES
from src.rag.service import retrieve_technical_knowledge


def _validate_corpus(corpus: list[tuple[str, str, dict[str, Any]]]) -> None:
    """Fail fast when a corpus row carries an unknown business_line_hint.

    Silent hint typos (e.g. "car_t" vs "car_t_car_nk") cause the Layer-1
    soft boost to produce 0 with no error — see the 2026-04-22 incident
    documented in project_rag_active_service_data_flow.md.
    """
    allowed = KNOWN_BUSINESS_LINES | {""}
    for _, query, ctx in corpus:
        hint = str(ctx.get("business_line_hint", "") or "").strip()
        if hint not in allowed:
            raise ValueError(
                f"business_line_hint={hint!r} is not in KNOWN_BUSINESS_LINES "
                f"for query {query!r}. Allowed: {sorted(KNOWN_BUSINESS_LINES)}"
            )


# Hypothesis labels ("high" / "medium" / "low" / "irrelevant") represent what
# we GUESS the confidence class should be — the whole point of this script is
# to check whether reality matches. Do not treat them as ground truth.
CORPUS: list[tuple[str, str, dict[str, Any]]] = [
    # --- I. High: explicit service + well-known technical intent ---
    ("high", "What is the service plan for CAR-T cell therapy?",
        {"business_line_hint": "car_t_car_nk"}),
    ("high", "What is the workflow for antibody production?",
        {"business_line_hint": "antibody"}),
    ("high", "What models do you support for mRNA LNP development?",
        {"business_line_hint": "mrna_lnp"}),
    ("high", "How long does CAR-T cell therapy development take?",
        {"business_line_hint": "car_t_car_nk"}),
    ("high", "What are the phases in antibody discovery?",
        {"business_line_hint": "antibody"}),

    # --- II. Medium: pronouns / term pairs / needs rewriting ---
    ("medium", "How does it work?",
        {"active_service_name": "CAR-T cell therapy", "business_line_hint": "car_t_car_nk"}),
    ("medium", "I need antibody purification for 1 liter",
        {"active_service_name": "Antibody production", "business_line_hint": "antibody"}),
    ("medium", "Quote for antibody production service",
        {"business_line_hint": "antibody"}),
    ("medium", "What's the timeline for this service?",
        {"active_service_name": "CAR-T cell therapy", "business_line_hint": "car_t_car_nk"}),

    # --- III. Non-technical but still customer-service-ish (should score low) ---
    ("low", "What's your contact phone number?", {}),
    ("low", "Do you ship to Europe?", {}),
    ("low", "When will I receive the invoice?", {}),
    ("low", "Who is your sales rep for antibody products?",
        {"business_line_hint": "antibody"}),

    # --- IV. Irrelevant / off-domain (should score lowest) ---
    ("irrelevant", "What's the weather today in Boston?", {}),
    ("irrelevant", "Can you recommend a good restaurant?", {}),
    ("irrelevant", "Tell me about COVID vaccines", {}),
]


def run_observation(csv_path: str | None = None) -> None:
    _validate_corpus(CORPUS)
    rows: list[dict[str, Any]] = []
    total = len(CORPUS)
    for idx, (category, query, ctx) in enumerate(CORPUS, start=1):
        print(f"[{idx}/{total}] ({category}) {query[:70]}", file=sys.stderr)
        result = retrieve_technical_knowledge(query=query, **ctx)
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
