"""Observation script: inspect contribution by query_variant_kind.

Usage:
    python tests/observe_rag_variant_contribution.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.service import retrieve_technical_knowledge
from tests.observe_rag_confidence import CORPUS


def run_observation() -> None:
    rows: list[dict[str, Any]] = []
    total = len(CORPUS)
    for idx, (category, query, ctx) in enumerate(CORPUS, start=1):
        print(f"[{idx}/{total}] ({category}) {query[:70]}", file=sys.stderr)
        result = retrieve_technical_knowledge(query=query, **ctx)
        observability = (result.get("retrieval_debug", {}) or {}).get("variant_observability", {}) or {}
        stats_by_kind = observability.get("stats_by_kind", {}) or {}
        for kind, stats in stats_by_kind.items():
            rows.append(
                {
                    "category": category,
                    "query": query[:48],
                    "kind": kind,
                    "group": stats.get("variant_group", ""),
                    "planned": stats.get("planned_queries", 0),
                    "unique": stats.get("unique_hits", 0),
                    "dedupe": stats.get("hits_survived_dedupe", 0),
                    "rerank": stats.get("hits_survived_rerank", 0),
                    "topk": stats.get("hits_in_final_top_k", 0),
                    "exclusive": stats.get("exclusive_hits", 0),
                }
            )

    _print_table(rows)


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no rows)")
        return
    headers = list(rows[0].keys())
    widths = {h: max(len(h), max(len(str(r[h])) for r in rows)) for h in headers}
    sep = "-+-".join("-" * widths[h] for h in headers)
    print(" | ".join(h.ljust(widths[h]) for h in headers))
    print(sep)
    for row in rows:
        print(" | ".join(str(row[h]).ljust(widths[h]) for h in headers))


if __name__ == "__main__":
    run_observation()
