"""
Baseline parser eval on held-out benchmark.

Loads data/labeled/parser_heldout_benchmark.json, runs the parser on each query
(cold-start, no prior turn context), then resolves dialogue_act from parser
signals. Compares predictions against gold labels and reports two independent
metrics:

- routing_accuracy: 3 项全命中 (route_splitter_flags set equality
  + dialogue_act value match + needs_human_review value match)
- retrieval_accuracy: primary_intent enum match

Outputs CSV per-row + console rollup with confusion matrix and per-flag F1.

Usage:
  PYTHONPATH=. python tests/eval_parser_heldout.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from src.ingestion.parser_adapter import (
    adapt_parsed_result_to_parser_signals,
    invoke_parser,
)
from src.routing.stages.dialogue_act import resolve_dialogue_act


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = REPO_ROOT / "data" / "labeled" / "parser_heldout_benchmark.json"
OUTPUT_DIR = REPO_ROOT / "outputs"

CORE_FLAGS = [
    "needs_price",
    "needs_quote",
    "needs_timeline",
    "needs_protocol",
    "needs_documentation",
    "needs_shipping_info",
    "needs_customization",
]

AUX_FLAGS = [
    "needs_troubleshooting",
    "needs_recommendation",
    "needs_regulatory_info",
    "needs_availability",
    "needs_comparison",
    "needs_sample",
    "needs_order_status",
    "needs_invoice",
    "needs_refund_or_cancellation",
]

ALL_INTENTS = [
    "product_inquiry",
    "technical_question",
    "workflow_question",
    "model_support_question",
    "service_plan_question",
    "pricing_question",
    "timeline_question",
    "customization_request",
    "documentation_request",
    "shipping_question",
    "troubleshooting",
    "order_support",
    "complaint",
    "follow_up",
    "general_info",
    "unknown",
]

DIALOGUE_ACTS = ["inquiry", "selection", "closing"]


def predict_one(query: str) -> dict:
    """Run parser + dialogue_act resolver on one query (cold-start)."""
    payload = invoke_parser(user_query=query)

    context = payload.get("context", {}) or {}
    pred_intent = context.get("semantic_intent", "unknown") or "unknown"
    pred_human_review = bool(context.get("needs_human_review", False))

    request_flags = payload.get("request_flags", {}) or {}
    pred_core_flags = sorted(f for f in CORE_FLAGS if request_flags.get(f, False))
    pred_aux_flags = sorted(f for f in AUX_FLAGS if request_flags.get(f, False))

    parser_signals = adapt_parsed_result_to_parser_signals(payload, source_query=query)
    da_result = resolve_dialogue_act(parser_signals, stateful_anchors=None)
    pred_dialogue_act = da_result.act

    return {
        "intent": pred_intent,
        "dialogue_act": pred_dialogue_act,
        "human_review": pred_human_review,
        "core_flags": pred_core_flags,
        "aux_flags": pred_aux_flags,
    }


def evaluate_one(gold: dict, pred: dict) -> dict:
    gold_core = sorted(gold.get("route_splitter_flags", []) or [])
    gold_aux = sorted(gold.get("auxiliary_flags", []) or [])

    intent_match = gold.get("primary_intent") == pred["intent"]
    da_match = gold.get("dialogue_act") == pred["dialogue_act"]
    hr_match = bool(gold.get("needs_human_review", False)) == pred["human_review"]
    core_match = gold_core == pred["core_flags"]
    aux_match = gold_aux == pred["aux_flags"]

    routing_pass = core_match and da_match and hr_match

    return {
        "intent_match": intent_match,
        "dialogue_act_match": da_match,
        "human_review_match": hr_match,
        "core_flags_match": core_match,
        "aux_flags_match": aux_match,
        "routing_accuracy": routing_pass,
        "retrieval_accuracy": intent_match,
    }


def main() -> int:
    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    n = len(benchmark)
    print(f"Loaded {n} held-out entries from {BENCHMARK_PATH}", file=sys.stderr)

    rows: list[dict] = []
    routing_pass = 0
    retrieval_pass = 0
    intent_confusion: dict[str, Counter] = defaultdict(Counter)
    da_confusion: dict[str, Counter] = defaultdict(Counter)
    hr_confusion: Counter = Counter()

    flag_tp: Counter = Counter()
    flag_fp: Counter = Counter()
    flag_fn: Counter = Counter()

    error_count = 0

    for idx, entry in enumerate(benchmark, start=1):
        query = entry["query"]
        entry_id = entry.get("id", f"idx_{idx}")
        print(f"[{idx}/{n}] {entry_id}", file=sys.stderr)

        try:
            pred = predict_one(query)
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            error_count += 1
            pred = {
                "intent": "ERROR",
                "dialogue_act": "ERROR",
                "human_review": False,
                "core_flags": [],
                "aux_flags": [],
            }

        eval_result = evaluate_one(entry, pred)

        if eval_result["routing_accuracy"]:
            routing_pass += 1
        if eval_result["retrieval_accuracy"]:
            retrieval_pass += 1

        intent_confusion[entry["primary_intent"]][pred["intent"]] += 1
        da_confusion[entry["dialogue_act"]][pred["dialogue_act"]] += 1
        hr_key = f"gold={entry['needs_human_review']}/pred={pred['human_review']}"
        hr_confusion[hr_key] += 1

        gold_all_flags = set(
            list(entry.get("route_splitter_flags", []) or [])
            + list(entry.get("auxiliary_flags", []) or [])
        )
        pred_all_flags = set(pred["core_flags"] + pred["aux_flags"])
        for flag in CORE_FLAGS + AUX_FLAGS:
            in_gold = flag in gold_all_flags
            in_pred = flag in pred_all_flags
            if in_gold and in_pred:
                flag_tp[flag] += 1
            elif in_pred and not in_gold:
                flag_fp[flag] += 1
            elif in_gold and not in_pred:
                flag_fn[flag] += 1

        rows.append({
            "idx": idx,
            "id": entry_id,
            "query_preview": query[:100].replace("\n", " "),
            "gold_intent": entry["primary_intent"],
            "pred_intent": pred["intent"],
            "intent_match": eval_result["intent_match"],
            "gold_dialogue_act": entry["dialogue_act"],
            "pred_dialogue_act": pred["dialogue_act"],
            "dialogue_act_match": eval_result["dialogue_act_match"],
            "gold_human_review": entry["needs_human_review"],
            "pred_human_review": pred["human_review"],
            "human_review_match": eval_result["human_review_match"],
            "gold_core_flags": ",".join(sorted(entry.get("route_splitter_flags", []) or [])),
            "pred_core_flags": ",".join(pred["core_flags"]),
            "core_flags_match": eval_result["core_flags_match"],
            "gold_aux_flags": ",".join(sorted(entry.get("auxiliary_flags", []) or [])),
            "pred_aux_flags": ",".join(pred["aux_flags"]),
            "aux_flags_match": eval_result["aux_flags_match"],
            "routing_accuracy": eval_result["routing_accuracy"],
            "retrieval_accuracy": eval_result["retrieval_accuracy"],
        })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUTPUT_DIR / f"eval_parser_heldout_{timestamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("\n" + "=" * 70)
    print("PARSER HELD-OUT BENCHMARK — BASELINE EVAL")
    print("=" * 70)
    print(f"Total queries: {n}  (errors: {error_count})")

    print(f"\n=== Main metrics (independent) ===")
    print(f"  routing_accuracy:   {routing_pass}/{n} = {100*routing_pass/n:5.1f}%")
    print(f"  retrieval_accuracy: {retrieval_pass}/{n} = {100*retrieval_pass/n:5.1f}%")

    da_pass = sum(1 for r in rows if r["dialogue_act_match"])
    hr_pass = sum(1 for r in rows if r["human_review_match"])
    cf_pass = sum(1 for r in rows if r["core_flags_match"])
    af_pass = sum(1 for r in rows if r["aux_flags_match"])
    print(f"\n=== routing_accuracy 分解 ===")
    print(f"  dialogue_act match:        {da_pass}/{n} = {100*da_pass/n:5.1f}%")
    print(f"  needs_human_review match:  {hr_pass}/{n} = {100*hr_pass/n:5.1f}%")
    print(f"  core flags set match:      {cf_pass}/{n} = {100*cf_pass/n:5.1f}%")
    print(f"  (aux flags set match {af_pass}/{n} = {100*af_pass/n:5.1f}% — not in main metric)")

    print(f"\n=== Per-flag P/R/F1 (skipped if never appears) ===")
    print(f"  {'flag':<35} {'tier':<6} {'P':>6} {'R':>6} {'F1':>6}  tp/fp/fn")
    for flag in CORE_FLAGS + AUX_FLAGS:
        tp = flag_tp[flag]
        fp = flag_fp[flag]
        fn = flag_fn[flag]
        if tp + fp + fn == 0:
            continue
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        tier = "CORE" if flag in CORE_FLAGS else "AUX"
        print(f"  {flag:<35} {tier:<6} {precision:>6.2f} {recall:>6.2f} {f1:>6.2f}  {tp}/{fp}/{fn}")

    print(f"\n=== primary_intent confusion(列出有出现的 gold intent)===")
    for gold_intent in ALL_INTENTS:
        preds = intent_confusion.get(gold_intent)
        if not preds:
            continue
        total = sum(preds.values())
        correct = preds.get(gold_intent, 0)
        confusions = {p: c for p, c in preds.items() if p != gold_intent}
        marker = "OK " if not confusions else "MIS"
        if confusions:
            print(f"  [{marker}] {gold_intent:<25} {correct}/{total}  → mispred: {confusions}")
        else:
            print(f"  [{marker}] {gold_intent:<25} {correct}/{total}")

    print(f"\n=== dialogue_act confusion ===")
    for gold_da in DIALOGUE_ACTS:
        preds = da_confusion.get(gold_da)
        if not preds:
            continue
        total = sum(preds.values())
        correct = preds.get(gold_da, 0)
        confusions = {p: c for p, c in preds.items() if p != gold_da}
        marker = "OK " if not confusions else "MIS"
        if confusions:
            print(f"  [{marker}] {gold_da:<12} {correct}/{total}  → mispred: {confusions}")
        else:
            print(f"  [{marker}] {gold_da:<12} {correct}/{total}")

    print(f"\n=== needs_human_review confusion ===")
    for k, v in sorted(hr_confusion.items()):
        print(f"  {k:<25} {v}")

    print(f"\nFull per-row CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
