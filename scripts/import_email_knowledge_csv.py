from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.email_knowledge_extraction import (
    EMAIL_KNOWLEDGE_JSONL_PATH,
    annotate_fact_records_for_review,
    parse_response_payload,
)


def _filter_facts_by_confidence(
    facts: list[dict],
    *,
    min_confidence: float,
) -> list[dict]:
    filtered: list[dict] = []
    for fact in facts:
        confidence = fact.get("confidence", 0.0)
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            score = 0.0
        if score >= min_confidence:
            filtered.append(fact)
    return filtered


def import_email_knowledge_csv(
    *,
    input_csv: str | Path,
    output_jsonl: str | Path = EMAIL_KNOWLEDGE_JSONL_PATH,
    response_column: str = "responses",
    min_confidence: float = 0.0,
    auto_approve_min_confidence: float | None = None,
    only_with_facts: bool = True,
) -> dict[str, int]:
    df = pd.read_csv(input_csv)
    if response_column not in df.columns:
        raise ValueError(f"列 '{response_column}' 不存在，可用列：{list(df.columns)}")

    out_path = Path(output_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_rows = len(df)
    written_rows = 0
    total_facts = 0

    with out_path.open("w", encoding="utf-8") as fout:
        for idx, row in df.iterrows():
            facts = parse_response_payload(row.get(response_column, ""))
            if min_confidence > 0:
                facts = _filter_facts_by_confidence(facts, min_confidence=min_confidence)
            if only_with_facts and not facts:
                continue

            record = annotate_fact_records_for_review(
                [{"email_index": int(row.get("Unnamed: 0", idx)), "facts": facts}]
            )[0]

            if auto_approve_min_confidence is not None and facts:
                confidences = []
                for fact in facts:
                    try:
                        confidences.append(float(fact.get("confidence", 0.0)))
                    except (TypeError, ValueError):
                        confidences.append(0.0)
                if confidences and min(confidences) >= auto_approve_min_confidence:
                    record["approved"] = True
                    record["review_status"] = "approved"

            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            written_rows += 1
            total_facts += len(facts)

    return {
        "total_rows": total_rows,
        "written_rows": written_rows,
        "total_facts": total_facts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从带 responses 列的邮件 CSV 生成可入库的邮件知识 JSONL")
    parser.add_argument("--input", required=True, help="输入 CSV 路径")
    parser.add_argument("--output", default=str(EMAIL_KNOWLEDGE_JSONL_PATH), help="输出 JSONL 路径")
    parser.add_argument("--response-column", default="responses", help="响应 JSON 所在列名")
    parser.add_argument("--min-confidence", type=float, default=0.0, help="过滤低于该置信度的 fact")
    parser.add_argument(
        "--auto-approve-min-confidence",
        type=float,
        default=None,
        help="若一行内全部 fact 都不低于该阈值，则自动标记 approved=true",
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        help="保留没有 facts 的记录（默认跳过）",
    )
    args = parser.parse_args()

    summary = import_email_knowledge_csv(
        input_csv=args.input,
        output_jsonl=args.output,
        response_column=args.response_column,
        min_confidence=args.min_confidence,
        auto_approve_min_confidence=args.auto_approve_min_confidence,
        only_with_facts=not args.include_empty,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "input": str(args.input),
                "output": str(args.output),
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
