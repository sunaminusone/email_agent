"""QuickBooks record → LLM-ready dict.

Phase 2 of the responder refactor. Tool-side serializer that projects
``extract_transaction_matches`` / ``extract_customer_matches`` output
into a shape the drafter LLM can consume without per-tool schema
knowledge in its system prompt.

Contract: ``docs/RESPONDER_DESIGN_V4.md`` ⭐ section.

What this serializer does:
  * Resolves QB sentinels in field names rather than values:
    ``email_status: "NotSet"`` → ``email_sent: false`` (drop email_status)
    ``email_status: "EmailSent"`` → ``email_sent: true``,
      ``email_sent_timestamp: "(not stored by QuickBooks)"``
    ``email_status: "NeedToSend"`` → ``email_sent: false, email_queued: true``
    Same shape for ``print_status``.
  * Renames ambiguous date / money fields:
    ``txn_date`` → ``transaction_date`` (the QB issue date)
    ``total_amt`` → ``total_amount``
    ``balance`` (Transaction) → ``outstanding_balance``
    ``balance`` (Customer) → ``total_outstanding_across_invoices``
      (customer-level balance is the SUM of all open invoices, not
      per-invoice — name reflects scope to prevent LLM confusion.)
  * Derives ``payment_status`` / ``days_past_due`` inline for Invoice
    transactions (mirrors ``extractors._derive_payment_status``; kept
    local to avoid responser → integrations import direction).
  * Drops the raw QB payload (``raw``) and customer_id (internal).
  * Drops None / empty fields so the LLM view stays narrow.

What this serializer does NOT do:
  * Touch primary_records — the raw view is preserved for debug / API
    consumers.
  * Strip address sub-dicts (``bill_addr`` / ``ship_addr`` on Customer)
    — those are already shaped reasonably and the drafter can read them.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_payment_status_inplace(raw: dict[str, Any]) -> None:
    """Mirror of ``extractors._derive_payment_status`` — kept local so QB
    serializer doesn't have to import from the responder layer.

    Adds ``payment_status`` / ``days_past_due`` to Invoice records.
    SalesReceipts skip (paid at point of sale by definition).
    """
    if (raw.get("entity") or "") != "Invoice":
        return

    balance = _coerce_float(raw.get("balance"))
    total = _coerce_float(raw.get("total_amt"))
    if balance is None:
        return

    if balance <= 0:
        raw["payment_status"] = _append_send_suffix("paid", raw)
        return

    due_date_str = str(raw.get("due_date") or "").strip()
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
        raw["days_past_due"] = delta_days
    elif delta_days == 0:
        base = "partial — due today" if is_partial else "due today"
    elif delta_days is not None:
        remaining = -delta_days
        suffix = "s" if remaining != 1 else ""
        prefix = "partial" if is_partial else "open"
        base = f"{prefix} · due in {remaining} day{suffix}"
    else:
        base = "partial" if is_partial else "open"

    raw["payment_status"] = _append_send_suffix(base, raw)


def _append_send_suffix(status: str, raw: dict[str, Any]) -> str:
    if str(raw.get("email_status") or "") == "NeedToSend":
        return f"{status} (not sent)"
    return status


def _resolve_email_sent(raw_status: Any, out: dict[str, Any]) -> None:
    """Sentinel → semantic booleans for email_status."""
    status = str(raw_status or "").strip()
    if not status:
        return
    if status == "EmailSent":
        out["email_sent"] = True
        out["email_sent_timestamp"] = "(not stored by QuickBooks)"
    elif status == "NeedToSend":
        out["email_sent"] = False
        out["email_queued"] = True
    elif status == "NotSet":
        out["email_sent"] = False
    else:
        # Unknown sentinel — pass through with the raw label so the
        # drafter can at least quote it.
        out["email_status"] = status


def _resolve_print_status(raw_status: Any, out: dict[str, Any]) -> None:
    status = str(raw_status or "").strip()
    if not status:
        return
    if status == "NotSet":
        out["printed"] = False
    elif status == "PrintComplete":
        out["printed"] = True
    else:
        out["print_status"] = status


def serialize_transaction_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Invoice / SalesReceipt / Estimate / etc. Derives payment_status
    in-place on ``raw`` first (so primary_records gets it too — matches
    extractors._derive_payment_status semantics), then projects into the
    llm view."""
    _derive_payment_status_inplace(raw)
    out: dict[str, Any] = {}

    for raw_key, llm_key in (
        ("entity", "entity"),
        ("doc_number", "doc_number"),
        ("customer_name", "customer_name"),
        ("billing_email", "billing_email"),
        ("txn_date", "transaction_date"),
        ("due_date", "due_date"),
        ("ship_date", "ship_date"),
        ("last_updated_at", "last_updated_at"),
        ("ship_city", "ship_city"),
        ("ship_country", "ship_country"),
        ("payment_status", "payment_status"),
        ("days_past_due", "days_past_due"),
    ):
        value = raw.get(raw_key)
        if value not in (None, ""):
            out[llm_key] = value

    # Money fields with semantic rename (outstanding_balance is clearer
    # than balance for transaction-scope; matches QBO web UI label).
    total = raw.get("total_amt")
    if total is not None:
        out["total_amount"] = total
    balance = raw.get("balance")
    if balance is not None:
        out["outstanding_balance"] = balance

    _resolve_email_sent(raw.get("email_status"), out)
    _resolve_print_status(raw.get("print_status"), out)
    return out


def serialize_customer_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Customer record — different field set + balance semantics."""
    out: dict[str, Any] = {}

    for raw_key, llm_key in (
        ("entity", "entity"),
        ("display_name", "display_name"),
        ("company_name", "company_name"),
        ("fully_qualified_name", "fully_qualified_name"),
        ("primary_email", "primary_email"),
        ("primary_phone", "primary_phone"),
        ("mobile_phone", "mobile_phone"),
        ("active", "active"),
        ("notes", "notes"),
    ):
        value = raw.get(raw_key)
        if value not in (None, ""):
            out[llm_key] = value

    # Customer-scope balance = TOTAL across all open invoices. Rename so
    # the LLM can't mistake it for a per-invoice figure.
    balance = raw.get("balance")
    if balance is None:
        balance = raw.get("open_balance")
    if balance is not None:
        out["total_outstanding_across_invoices"] = balance

    # Pass shipping / billing addresses through unchanged — they're
    # already nested dicts that read naturally.
    for addr_key in ("bill_addr", "ship_addr"):
        addr = raw.get(addr_key)
        if isinstance(addr, dict) and addr:
            out[addr_key] = addr

    return out


def serialize_qb_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Entry point — dispatch by entity. Caller (QB tool wrapper) invokes
    this on every match before emitting llm_records."""
    entity = (raw.get("entity") or "").strip()
    if entity == "Customer":
        return serialize_customer_record(raw)
    return serialize_transaction_record(raw)


__all__ = [
    "serialize_qb_record",
    "serialize_transaction_record",
    "serialize_customer_record",
]
