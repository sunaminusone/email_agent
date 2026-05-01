from __future__ import annotations

from datetime import date
from typing import Any

from src.common.execution_models import ExecutedToolCall
from src.responser.models import ResponseInput
from src.documents.retrieval.service_documents import get_primary_service_document_link

_TOOL_BUCKETS: dict[str, str] = {
    "historical_thread_tool": "historical",
    "technical_rag_tool": "technical_docs",
    "document_lookup_tool": "document_files",
    "catalog_lookup_tool": "structured",
    "pricing_lookup_tool": "structured",
    "customer_lookup_tool": "operational",
    "invoice_lookup_tool": "operational",
    "order_lookup_tool": "operational",
    "shipping_lookup_tool": "operational",
}


def collect_calls_by_bucket(
    response_input: ResponseInput,
) -> dict[str, list[ExecutedToolCall]]:
    """Iterate every executed tool call once and bucket by tool_name."""
    buckets: dict[str, list[ExecutedToolCall]] = {
        "historical": [],
        "technical_docs": [],
        "document_files": [],
        "structured": [],
        "operational": [],
        "unknown": [],
    }
    for call in response_input.execution_result.executed_calls:
        if call.result is None:
            continue
        bucket = _TOOL_BUCKETS.get(call.tool_name, "unknown")
        buckets[bucket].append(call)
    return buckets


def extract_historical_threads(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    for call in calls:
        threads = (call.result.structured_facts or {}).get("threads") or []
        if isinstance(threads, list) and threads:
            return threads
    return []


def extract_technical_doc_matches(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    for call in calls:
        matches = (call.result.structured_facts or {}).get("matches") or []
        if isinstance(matches, list) and matches:
            return matches[:5]
    return []


def extract_retrieval_confidence(calls: list[ExecutedToolCall]) -> dict[str, Any]:
    for call in calls:
        confidence = (call.result.structured_facts or {}).get("retrieval_confidence") or {}
        if isinstance(confidence, dict) and confidence:
            return confidence
    return {}


def extract_document_files(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for call in calls:
        matches = call.result.primary_records or []
        for match in matches:
            if isinstance(match, dict):
                out.append(match)
    return out[:5]


def extract_structured_records(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for call in calls:
        facts = call.result.structured_facts or {}
        records = facts.get("pricing_records")
        if not records:
            records = call.result.primary_records or []
        for record in records:
            if not isinstance(record, dict):
                continue
            annotated = dict(record)
            annotated["_source_tool"] = call.tool_name
            out.append(annotated)
    return out[:8]


def extract_operational_records(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for call in calls:
        records = call.result.primary_records or []
        for record in records:
            if not isinstance(record, dict):
                continue
            annotated = dict(record)
            annotated["_source_tool"] = call.tool_name
            _derive_payment_status(annotated)
            out.append(annotated)
    return out[:8]


PAYMENT_STATUS_VOCABULARY = """\
- `paid` — balance is 0
- `open` / `partial` — balance > 0, no due date on file
- `open · due in N day(s)` / `partial · due in N day(s)` — due in the future
- `due today` / `partial — due today`
- `overdue (N day(s))` / `partial — overdue (N day(s))` — past due
Any value may be suffixed `(not sent)` when `email_status` is `NeedToSend`
(QB has the document queued but it has never been emailed)."""


def _derive_payment_status(record: dict[str, Any]) -> None:
    """Add `payment_status` / `days_past_due` to QuickBooks Invoice records.

    QBO's REST API does not return Open/Partial/Overdue/Paid — the QBO web
    UI derives it from Balance vs TotalAmt vs DueDate. We replicate that
    derivation so the CSR (and the drafter) don't have to do date+amount
    arithmetic in their head. SalesReceipts are paid at point of sale, so
    we skip them.

    The vocabulary of values produced lives in ``PAYMENT_STATUS_VOCABULARY``
    above — that constant is also spliced into the draft LLM system prompt,
    so any change here must be reflected there (single source of truth).
    """
    if (record.get("entity") or "") != "Invoice":
        return

    balance = _coerce_float(record.get("balance"))
    total = _coerce_float(record.get("total_amt"))
    if balance is None:
        return

    if balance <= 0:
        record["payment_status"] = _append_send_suffix("paid", record)
        return

    due_date_str = str(record.get("due_date") or "").strip()
    due: date | None = None
    if due_date_str:
        try:
            due = date.fromisoformat(due_date_str[:10])
        except ValueError:
            due = None

    is_partial = total is not None and 0 < balance < total
    delta_days = (date.today() - due).days if due is not None else None

    if delta_days is not None and delta_days > 0:
        suffix = "s" if delta_days != 1 else ""
        prefix = "partial — overdue" if is_partial else "overdue"
        base = f"{prefix} ({delta_days} day{suffix})"
        record["days_past_due"] = delta_days
    elif delta_days == 0:
        base = "partial — due today" if is_partial else "due today"
    elif delta_days is not None:
        remaining = -delta_days
        suffix = "s" if remaining != 1 else ""
        prefix = "partial" if is_partial else "open"
        base = f"{prefix} · due in {remaining} day{suffix}"
    else:
        base = "partial" if is_partial else "open"

    record["payment_status"] = _append_send_suffix(base, record)


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_send_suffix(status: str, record: dict[str, Any]) -> str:
    if str(record.get("email_status") or "") == "NeedToSend":
        return f"{status} (not sent)"
    return status


def collect_routing_notes(response_input: ResponseInput) -> list[str]:
    notes: list[str] = []
    for outcome in response_input.group_outcomes:
        rd = getattr(outcome, "route_decision", None)
        if rd is None:
            continue
        reason = getattr(rd, "reason", "") or ""
        if reason.startswith("AI_ROUTING_NOTE"):
            notes.append(reason)
    return notes


def resolve_primary_service_document(
    response_input: ResponseInput,
) -> tuple[dict[str, Any] | None, str]:
    """Mint a presigned link for the primary service document, when applicable.

    Returns (None, "") in three cases: the customer didn't request docs,
    no service was resolved, or the resolved service has no primary
    document. Returns (None, error_message) only on infrastructure
    failure (S3 / RDS).
    """
    requested = bool(
        response_input.demand_profile is not None
        and "needs_documentation" in response_input.demand_profile.active_request_flags
    )
    if not requested:
        for outcome in response_input.group_outcomes:
            scoped_demand = getattr(outcome, "scoped_demand", None)
            if scoped_demand is not None and "needs_documentation" in getattr(scoped_demand, "request_flags", []):
                requested = True
                break
    if not requested:
        return None, ""

    service_name = ""
    resolved = response_input.resolved_object_state
    if resolved is not None:
        for candidate in (resolved.primary_object, resolved.active_object, *resolved.secondary_objects):
            if candidate is None or candidate.object_type != "service":
                continue
            service_name = str(
                candidate.display_name or candidate.canonical_value or candidate.identifier or ""
            ).strip()
            if service_name:
                break
    if not service_name:
        return None, ""

    try:
        return get_primary_service_document_link(service_name), ""
    except Exception as exc:
        return None, str(exc)
