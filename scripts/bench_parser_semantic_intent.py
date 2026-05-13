#!/usr/bin/env python3
"""Benchmark parser `semantic_intent` classification against a labeled dataset.

Two intended datasets (both using the same JSON schema):

- `data/labeled/parser_coverage_suite.json`   : hand-written design-challenge set
                                                 (hard gate — every row must hit)
- `data/labeled/parser_heldout_benchmark.json`: real-inbox held-out benchmark
                                                 (soft metrics — macro-F1, confusion)

Schema (list of dicts):
    {"id": str, "query": str, "semantic_intent": str,
     "conversation_history": [{"role": "customer|agent", "content": str}]?}

Output: per-row hit/miss + per-intent support/precision/recall + confusion matrix
+ macro-F1. Optional `--repeat N` re-runs each case to surface sampling variance.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Parser semantic_intent benchmark.")
    p.add_argument("--dataset", required=True, help="Path to labeled JSON dataset.")
    p.add_argument("--ids", nargs="*", default=[], help="Optional id filter.")
    p.add_argument("--limit", type=int, default=0, help="Optional row limit for dev runs.")
    p.add_argument("--repeat", type=int, default=1, help="Re-run each case N times (stability).")
    p.add_argument("--output", default="", help="Optional path to write full result JSON.")
    return p.parse_args()


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _convert_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    # Normalize customer/agent → user/assistant for parser input.
    mapped = []
    for turn in history or []:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role == "customer":
            role = "user"
        elif role == "agent":
            role = "assistant"
        mapped.append({"role": role, "content": content})
    return mapped


def _run_parser_once(query: str, history: list[dict[str, str]]) -> str:
    from src.ingestion.parser_adapter import invoke_parser

    payload = invoke_parser(
        user_query=query,
        conversation_history=history,
        attachments=[],
    )
    ctx = payload.get("context") or {}
    return str(ctx.get("semantic_intent") or "").strip()


def _bench_one(case: dict[str, Any], repeat: int) -> dict[str, Any]:
    query = str(case.get("query") or "").strip()
    history = _convert_history(case.get("conversation_history") or [])
    preds: list[str] = []
    for _ in range(max(1, repeat)):
        preds.append(_run_parser_once(query, history))
    # Stability: modal prediction + agreement rate over repeats.
    counts = Counter(preds)
    modal, modal_hits = counts.most_common(1)[0]
    agreement = modal_hits / len(preds)
    expected = str(case.get("semantic_intent") or "").strip()
    return {
        "id": case.get("id"),
        "query": query,
        "expected": expected,
        "predicted_runs": preds,
        "modal_prediction": modal,
        "agreement": round(agreement, 3),
        "hit": modal == expected,
    }


def _confusion_matrix(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        matrix[r["expected"]][r["modal_prediction"]] += 1
    return {k: dict(v) for k, v in matrix.items()}


def _per_intent_metrics(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    gold = Counter(r["expected"] for r in results)
    pred = Counter(r["modal_prediction"] for r in results)
    tp = Counter(r["expected"] for r in results if r["hit"])
    metrics = {}
    for intent in sorted(set(gold) | set(pred)):
        support = gold[intent]
        precision = tp[intent] / pred[intent] if pred[intent] else 0.0
        recall = tp[intent] / gold[intent] if gold[intent] else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        metrics[intent] = {
            "support": support,
            "predicted": pred[intent],
            "hits": tp[intent],
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }
    return metrics


def _print_report(dataset_path: Path, results: list[dict[str, Any]], repeat: int) -> None:
    total = len(results)
    hits = sum(1 for r in results if r["hit"])
    acc = hits / total if total else 0.0

    print("=" * 78)
    print(f"  parser semantic_intent benchmark — {dataset_path.name}")
    print(f"  rows: {total}  |  hits: {hits}  |  accuracy: {acc:.3f}  |  repeat: {repeat}")
    print("=" * 78)

    # Per-row miss detail (only misses)
    misses = [r for r in results if not r["hit"]]
    if misses:
        print(f"\n── misses ({len(misses)}) ──")
        for r in misses:
            runs = ",".join(r["predicted_runs"]) if repeat > 1 else r["modal_prediction"]
            q = (r["query"][:88] + "...") if len(r["query"]) > 88 else r["query"]
            print(f"  [{r['id']}]  exp={r['expected']}  got={runs}  agr={r['agreement']}")
            print(f"    Q: {q}")

    # Per-intent
    print("\n── per-intent ──")
    metrics = _per_intent_metrics(results)
    print(f"  {'intent':<26}{'support':>8}{'pred':>6}{'hits':>6}{'prec':>7}{'rec':>7}{'f1':>7}")
    for intent, m in metrics.items():
        print(
            f"  {intent:<26}{m['support']:>8}{m['predicted']:>6}{m['hits']:>6}"
            f"{m['precision']:>7.3f}{m['recall']:>7.3f}{m['f1']:>7.3f}"
        )

    # Macro-F1 (mean F1 across intents present in gold)
    gold_intents = [i for i, m in metrics.items() if m["support"] > 0]
    macro_f1 = (sum(metrics[i]["f1"] for i in gold_intents) / len(gold_intents)) if gold_intents else 0.0
    print(f"\n  macro-F1 (over {len(gold_intents)} gold intents): {macro_f1:.3f}")

    # Confusion matrix (only non-diagonal cells)
    matrix = _confusion_matrix(results)
    off_diag = [
        (gold, pred, n)
        for gold, preds in matrix.items()
        for pred, n in preds.items()
        if gold != pred
    ]
    if off_diag:
        print("\n── confusion (gold → predicted) ──")
        off_diag.sort(key=lambda x: -x[2])
        for gold, pred, n in off_diag:
            print(f"  {gold:<26} → {pred:<26} {n}")

    # Stability: flag low-agreement rows when repeat > 1
    if repeat > 1:
        unstable = [r for r in results if r["agreement"] < 1.0]
        if unstable:
            print(f"\n── unstable rows (agreement < 1.0) ──  {len(unstable)}")
            for r in unstable:
                print(f"  [{r['id']}]  runs={r['predicted_runs']}  agr={r['agreement']}")


def main() -> int:
    args = _parse_args()

    dataset_path = Path(args.dataset).resolve()
    cases = _load_dataset(dataset_path)

    selected_ids = {i.strip() for i in args.ids if i.strip()}
    if selected_ids:
        cases = [c for c in cases if c.get("id") in selected_ids]
    if args.limit:
        cases = cases[: args.limit]

    results = [_bench_one(c, args.repeat) for c in cases]
    _print_report(dataset_path, results, args.repeat)

    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "dataset": str(dataset_path),
                    "repeat": args.repeat,
                    "results": results,
                    "per_intent": _per_intent_metrics(results),
                    "confusion": _confusion_matrix(results),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
