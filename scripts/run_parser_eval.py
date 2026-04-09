#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN_SET_PATH = ROOT / "data" / "labeled" / "parser_eval_golden_set.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run parser eval against a golden set.")
    parser.add_argument(
        "--path",
        default=str(DEFAULT_GOLDEN_SET_PATH),
        help="Path to the parser eval golden set JSON file.",
    )
    parser.add_argument(
        "--ids",
        nargs="*",
        default=[],
        help="Optional case ids to run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON results.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write the full eval payload as JSON.",
    )
    return parser.parse_args()


def _normalize_list(values: Any) -> list[str]:
    cleaned = [str(value or "").strip() for value in (values or [])]
    return sorted([value for value in cleaned if value], key=str.lower)


def _normalize_scalar(value: Any) -> str:
    return str(value or "").strip()


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_actual(result: Any) -> dict[str, Any]:
    return {
        "primary_intent": _normalize_scalar(result.context.primary_intent),
        "product_names": _normalize_list(result.entities.product_names),
        "catalog_numbers": _normalize_list(result.entities.catalog_numbers),
        "service_names": _normalize_list(result.entities.service_names),
        "order_numbers": _normalize_list(result.entities.order_numbers),
        "referenced_prior_context": _normalize_scalar(result.open_slots.referenced_prior_context),
        "needs_documentation": bool(result.request_flags.needs_documentation),
        "needs_timeline": bool(result.request_flags.needs_timeline),
        "needs_price": bool(result.request_flags.needs_price),
        "needs_quote": bool(result.request_flags.needs_quote),
        "needs_shipping_info": bool(result.request_flags.needs_shipping_info),
    }


def _compare_case(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    field_results: dict[str, bool] = {}
    mismatches: dict[str, dict[str, Any]] = {}

    for field, expected_value in expected.items():
        if isinstance(expected_value, list):
            actual_value = _normalize_list(actual.get(field, []))
            normalized_expected = _normalize_list(expected_value)
        elif isinstance(expected_value, bool):
            actual_value = bool(actual.get(field, False))
            normalized_expected = expected_value
        else:
            actual_value = _normalize_scalar(actual.get(field, ""))
            normalized_expected = _normalize_scalar(expected_value)

        matched = actual_value == normalized_expected
        field_results[field] = matched
        if not matched:
            mismatches[field] = {
                "expected": normalized_expected,
                "actual": actual_value,
            }

    return {
        "passed": all(field_results.values()),
        "field_results": field_results,
        "mismatches": mismatches,
    }


def main() -> int:
    args = parse_args()

    from src.parser.service import parse_user_input

    case_path = Path(args.path).resolve()
    all_cases = _load_cases(case_path)
    selected_ids = {case_id.strip() for case_id in args.ids if case_id.strip()}
    cases = [case for case in all_cases if not selected_ids or case["id"] in selected_ids]

    results: list[dict[str, Any]] = []
    for case in cases:
        query = str(case.get("query") or "").strip()
        conversation_history = list(case.get("conversation_history") or [])
        attachments = list(case.get("attachments") or [])
        parsed = parse_user_input(
            user_query=query,
            conversation_history=conversation_history,
            attachments=attachments,
        )
        actual = _extract_actual(parsed)
        comparison = _compare_case(case.get("expected", {}), actual)
        results.append(
            {
                "id": case["id"],
                "query": query,
                "passed": comparison["passed"],
                "field_results": comparison["field_results"],
                "mismatches": comparison["mismatches"],
                "expected": case.get("expected", {}),
                "actual": actual,
            }
        )

    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    intent_hits = sum(
        1
        for result in results
        if result["field_results"].get("primary_intent", False)
    )
    metrics = {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "case_pass_rate": round((passed / total), 4) if total else 0.0,
        "intent_accuracy": round((intent_hits / total), 4) if total else 0.0,
    }

    payload = {
        "golden_set_path": str(case_path),
        "metrics": metrics,
        "results": results,
    }

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"Parser eval: {passed}/{total} cases passed")
    print(f"Intent accuracy: {intent_hits}/{total}")
    print(f"Golden set: {case_path}")
    print("---")
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {result['id']}: {result['query']}")
        if result["mismatches"]:
            for field, mismatch in result["mismatches"].items():
                print(f"  - {field}: expected={mismatch['expected']} actual={mismatch['actual']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
