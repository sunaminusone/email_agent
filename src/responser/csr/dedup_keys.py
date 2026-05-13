"""Presenter-side deduplication of executed tool calls.

The executor keeps a raw ``executed_calls`` list — one entry per dispatch,
including cross-group cache reuses (engine._dispatch_selections synthesizes
a new ExecutedToolCall with the same result when another intent group has
already called the tool) and retry-with-fallback. That raw list is the
right thing for audit / debug.

For the responder, we want a deduped view: at most one ExecutedToolCall
per ``tool_name``, with ``primary_records`` from all duplicate calls
collapsed via a tool-specific identity function. ``merged_results`` on
ExecutionResult is already deduped at the structured_facts level (merger.py
overwrites by tool_name) — this module is the equivalent for the per-call
records list.

Unknown tools (no entry in ``_DEDUP_KEY``) are passed through unchanged
with a warning, so a new tool can't silently regress.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from src.common.execution_models import ExecutedToolCall
from src.tools.models import ToolResult


logger = logging.getLogger(__name__)


# Identity function per tool — what makes two records "the same record".
# When adding a new tool: pick the field that uniquely identifies a record
# from that tool's perspective, falling back through plausible alternatives.
# Empty string return = no identity available → record cannot be deduped
# (kept as-is to avoid losing data).
_DEDUP_KEY: dict[str, Callable[[dict[str, Any]], str]] = {
    "document_lookup_tool": lambda r: (r.get("storage_url") or "").strip(),
    "catalog_lookup_tool":  lambda r: (r.get("catalog_no") or r.get("id") or "").strip(),
    "pricing_lookup_tool":  lambda r: "::".join([
        str(r.get("catalog_no") or ""),
        str(r.get("plan_name") or ""),
        str(r.get("phase_name") or ""),
    ]).strip(":"),
    "order_lookup_tool":    lambda r: (r.get("doc_number") or r.get("id") or "").strip(),
    "invoice_lookup_tool":  lambda r: (r.get("doc_number") or r.get("id") or "").strip(),
    "shipping_lookup_tool": lambda r: (r.get("tracking_number") or r.get("doc_number") or "").strip(),
    "customer_lookup_tool": lambda r: (r.get("id") or r.get("email") or "").strip(),
    "historical_thread_tool": lambda r: (r.get("thread_key") or r.get("id") or "").strip(),
    "technical_rag_tool":   lambda r: (r.get("chunk_id") or r.get("source_path") or "").strip(),
}


# Status priority for the synthesized merged call. "ok" wins if any source
# call returned ok; otherwise progressively weaker statuses.
_STATUS_PRIORITY = ("ok", "partial", "error", "empty")


def _bucket_has_aligned_llm_records(bucket: list[ExecutedToolCall]) -> bool:
    """True iff every call in the bucket has llm_records aligned 1:1 with
    its primary_records AND at least one call carries non-empty llm content.

    Mixed mode (one call migrated, another not) falls back to empty
    llm_records on the merged call so the extractor reads primary directly
    rather than mixing apples and oranges.
    """
    any_non_empty = False
    for call in bucket:
        if call.result is None:
            continue
        primary = call.result.primary_records or []
        llm = call.result.llm_records or []
        if llm:
            any_non_empty = True
            if len(llm) != len(primary):
                return False
        elif primary:
            # Has primary records but no llm — fallback mode for this call.
            return False
    return any_non_empty


def dedupe_calls(calls: list[ExecutedToolCall]) -> list[ExecutedToolCall]:
    """Return a deduped view of executed_calls — one entry per tool_name.

    Order of first appearance is preserved. For each tool with >1 entry,
    primary_records are merged via the tool's identity function; the
    representative call takes role/request from the primary call in the
    bucket (or the first), and status from the best status across the
    bucket.
    """
    grouped: dict[str, list[ExecutedToolCall]] = {}
    order: list[str] = []
    for call in calls:
        if call.tool_name not in grouped:
            grouped[call.tool_name] = []
            order.append(call.tool_name)
        grouped[call.tool_name].append(call)

    out: list[ExecutedToolCall] = []
    for tool_name in order:
        bucket = grouped[tool_name]
        if len(bucket) == 1:
            out.append(bucket[0])
            continue

        identity_fn = _DEDUP_KEY.get(tool_name)
        if identity_fn is None:
            logger.warning(
                "dedupe_calls: no identity function registered for tool %s; "
                "keeping %d duplicate calls in the responder view",
                tool_name, len(bucket),
            )
            out.extend(bucket)
            continue

        out.append(_merge_bucket(bucket, identity_fn))
    return out


def _merge_bucket(
    bucket: list[ExecutedToolCall],
    identity_fn: Callable[[dict[str, Any]], str],
) -> ExecutedToolCall:
    """Collapse a list of same-tool calls into one synthesized call.

    Strategy:
      * request / role: take from the primary call in the bucket if any;
        otherwise the first call.
      * primary_records: union of all calls' records, deduped by identity_fn
        (records with empty identity are kept as-is — we can't safely dedupe
        them without false collisions).
      * llm_records: identity ALWAYS computes on primary_records — the
        llm view rides along at the same source index. If any source call
        has a length mismatch or missing llm_records, the merged bucket
        falls back to empty llm_records (extractor then reads primary).
        See docs/RESPONDER_DESIGN_V4.md ⭐ section.
      * structured_facts / snippets / artifacts: shallow-merge so the merged
        result still exposes everything any source call carried (cross-group
        cache reuse means most of the bucket shares identical results, so
        this is rarely lossy).
      * status: best of bucket per ``_STATUS_PRIORITY``.
      * latency_ms: sum (cumulative time across all calls in the bucket).
      * error: first non-empty error string from the bucket.
    """
    base = next((c for c in bucket if c.role == "primary"), bucket[0])

    # Decide once: can we sync-merge llm_records this bucket? Requires
    # every source call to have llm_records aligned with its primary, AND
    # at least one call to actually carry non-empty llm content.
    sync_llm = _bucket_has_aligned_llm_records(bucket)

    seen_keys: set[str] = set()
    merged_records: list[dict[str, Any]] = []
    merged_llm_records: list[dict[str, Any]] = []
    merged_facts: dict[str, Any] = {}
    merged_snippets: list[dict[str, Any]] = []
    merged_artifacts: list[dict[str, Any]] = []
    errors_seen: list[str] = []

    for call in bucket:
        result = call.result
        if result is None:
            continue
        primary = result.primary_records or []
        llm_view = result.llm_records or [] if sync_llm else []
        for i, record in enumerate(primary):
            if not isinstance(record, dict):
                continue
            key = identity_fn(record)
            if not key:
                # No identity → keep without dedup (better than dropping).
                merged_records.append(record)
                if sync_llm:
                    merged_llm_records.append(llm_view[i])
                continue
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged_records.append(record)
            if sync_llm:
                merged_llm_records.append(llm_view[i])
        merged_facts.update(result.structured_facts or {})
        merged_snippets.extend(result.unstructured_snippets or [])
        merged_artifacts.extend(result.artifacts or [])
        if result.errors:
            errors_seen.extend(result.errors)

    statuses = {c.status for c in bucket}
    merged_status = next((s for s in _STATUS_PRIORITY if s in statuses), "empty")

    merged_result = ToolResult(
        tool_name=base.tool_name,
        status=merged_status,
        primary_records=merged_records,
        llm_records=merged_llm_records,
        structured_facts=merged_facts,
        unstructured_snippets=merged_snippets,
        artifacts=merged_artifacts,
        errors=errors_seen,
    )

    return ExecutedToolCall(
        call_id=base.call_id,
        tool_name=base.tool_name,
        role=base.role,
        status=merged_status,
        request=base.request,
        result=merged_result,
        latency_ms=sum(c.latency_ms for c in bucket),
        error=next((c.error for c in bucket if c.error), ""),
    )
