from __future__ import annotations

from typing import Any

_HISTORICAL_STRONG_MATCH = 0.75
_HISTORICAL_USABLE_MATCH = 0.55


def filter_historical_threads(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not threads:
        return []
    strong = [t for t in threads if float(t.get("best_score", 0.0) or 0.0) >= _HISTORICAL_STRONG_MATCH]
    if strong:
        return strong[:3]
    usable = [t for t in threads if float(t.get("best_score", 0.0) or 0.0) >= _HISTORICAL_USABLE_MATCH]
    return usable[:2]


def build_trust_signal(
    *,
    raw_historical_threads: list[dict[str, Any]],
    surfaced_historical_threads: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    retrieval_confidence: dict[str, Any],
    structured_records: list[dict[str, Any]],
    operational_records: list[dict[str, Any]],
) -> dict[str, Any]:
    retrieval_quality_tier = str(retrieval_confidence.get("level") or "unknown")
    top_doc_score = max(
        [float(m.get("final_score") or m.get("base_score") or 0.0) for m in documents],
        default=0.0,
    )
    historical_best_score = max(
        [float(t.get("best_score", 0.0) or 0.0) for t in surfaced_historical_threads],
        default=0.0,
    )
    has_live_data = bool(structured_records or operational_records)

    if has_live_data:
        grounding_status = "grounded"
    elif surfaced_historical_threads and retrieval_quality_tier == "high":
        grounding_status = "grounded"
    elif surfaced_historical_threads or documents:
        grounding_status = "weakly_grounded"
    else:
        grounding_status = "ungrounded"

    summary_parts: list[str] = []
    if structured_records:
        summary_parts.append(f"{len(structured_records)} live catalog/pricing record(s)")
    if operational_records:
        summary_parts.append(f"{len(operational_records)} operational record(s)")
    if surfaced_historical_threads:
        strength = "strong" if grounding_status == "grounded" and not has_live_data else "usable"
        summary_parts.append(
            f"{len(surfaced_historical_threads)} {strength} historical thread(s)"
        )
    if documents:
        summary_parts.append(f"{len(documents)} document match(es)")

    if grounding_status == "grounded":
        if has_live_data:
            summary = "Grounded in live database: " + ", ".join(summary_parts) + "."
        else:
            summary = "Based on " + " and ".join(summary_parts) + "."
    elif grounding_status == "weakly_grounded":
        summary = (
            "Partial evidence only: " + ", ".join(summary_parts)
            + ". CSR should verify details before sending."
        )
    else:
        summary = (
            "No live data, strong historical replies, or relevant documents were retrieved. "
            "Treat the draft as a cautious starting point, not an evidence-backed answer."
        )

    return {
        "grounding_status": grounding_status,
        "summary": summary,
        "retrieval_quality_tier": retrieval_quality_tier,
        "historical_threads_raw": len(raw_historical_threads),
        "historical_threads_used": len(surfaced_historical_threads),
        "historical_best_score": round(historical_best_score, 4),
        "documents_used": len(documents),
        "top_document_score": round(top_doc_score, 4),
        "structured_records_used": len(structured_records),
        "operational_records_used": len(operational_records),
        "has_live_data": has_live_data,
    }
