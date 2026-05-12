"""Phase 0 contract tests for the upcoming ``ToolResult.llm_records`` field.

These guard the contract introduced in
``docs/RESPONDER_DESIGN_V4.md`` ⭐ section. The contract:

1. Extractors prefer ``call.result.llm_records`` when present.
2. Extractors fall back to ``call.result.primary_records`` when llm_records
   is absent / empty — current behavior, must NOT regress as the field rolls
   out.
3. ``dedupe_calls`` collapses same-tool repeats while keeping
   ``llm_records`` and ``primary_records`` 1:1 aligned (identity always
   computed on primary; llm view rides along by index).

Tests (1) and (3) require the ``llm_records`` field on
:class:`src.tools.models.ToolResult`. They are marked ``skipif`` until
Phase 1 step 1 lands. Test (2) runs today as the regression guard for the
pre-migration fallback path.
"""
from __future__ import annotations

import pytest

from src.common.execution_models import ExecutedToolCall
from src.responser.csr.dedup_keys import dedupe_calls
from src.responser.csr.extractors import (
    extract_operational_records,
    extract_structured_records,
)
from src.tools.models import ToolRequest, ToolResult


_LLM_RECORDS_FIELD_PRESENT = "llm_records" in ToolResult.model_fields


def _make_call(
    *,
    tool_name: str,
    primary_records: list[dict] | None = None,
    role: str = "primary",
    status: str = "ok",
    llm_records: list[dict] | None = None,
) -> ExecutedToolCall:
    """Build a synthetic ExecutedToolCall. ``llm_records`` arg is silently
    dropped when the field doesn't exist yet — lets tests be written for the
    target shape today without breaking the skipif-gated suite."""
    result_kwargs: dict = {
        "tool_name": tool_name,
        "status": status,
        "primary_records": list(primary_records or []),
    }
    if _LLM_RECORDS_FIELD_PRESENT and llm_records is not None:
        result_kwargs["llm_records"] = list(llm_records)

    return ExecutedToolCall(
        call_id="c1",
        tool_name=tool_name,
        role=role,
        status=status,
        request=ToolRequest(tool_name=tool_name),
        result=ToolResult(**result_kwargs),
    )


# ---------------------------------------------------------------------------
# (2) Fallback path — runs today as the regression guard
# ---------------------------------------------------------------------------


def test_extractor_uses_primary_records_when_llm_records_absent() -> None:
    """Current behavior: extractors read ``primary_records`` directly.

    Migration must not regress this. After Phase 1 step 1 the extractor
    will prefer ``llm_records``, but when a tool has not yet emitted it,
    fallback must still surface the raw records.
    """
    call = _make_call(
        tool_name="catalog_lookup_tool",
        primary_records=[
            {"catalog_no": "PM-CAR1000", "name": "Mock CD28 CAR-T", "price": 1259},
        ],
    )
    records = extract_structured_records([call])
    assert len(records) == 1
    assert records[0]["catalog_no"] == "PM-CAR1000"
    # Annotation that extract_structured_records always adds, independent of
    # which source list it pulls from.
    assert records[0]["_source_tool"] == "catalog_lookup_tool"


def test_operational_extractor_uses_primary_records_when_llm_records_absent() -> None:
    """Same regression guard for the operational path."""
    call = _make_call(
        tool_name="invoice_lookup_tool",
        primary_records=[
            {"doc_number": "INV-7890", "total_amt": 5000, "balance": 0},
        ],
    )
    records = extract_operational_records([call])
    assert len(records) == 1
    assert records[0]["doc_number"] == "INV-7890"
    assert records[0]["_source_tool"] == "invoice_lookup_tool"


# ---------------------------------------------------------------------------
# (1) Preference path — skipped until Phase 1 step 1 adds the field
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _LLM_RECORDS_FIELD_PRESENT,
    reason="Phase 1 step 1: pending ToolResult.llm_records field.",
)
def test_extractor_prefers_llm_records_over_primary_records() -> None:
    """When ``llm_records`` is present, extractors must read from it.

    The raw record's ``wb_dilution`` field is preserved; the llm record
    might rename or normalize it — extractor must surface the llm view.
    """
    call = _make_call(
        tool_name="catalog_lookup_tool",
        primary_records=[
            {"catalog_no": "10007", "wb_dilution": "1/500 - 1/2000", "sequence": "full"},
        ],
        llm_records=[
            # Hypothetical llm-ready shape — sentinel resolved, schema-agnostic name.
            {"catalog_no": "10007", "wb_dilution": "1/500 - 1/2000",
             "immunogen_sequence": "(not on file)"},
        ],
    )
    records = extract_structured_records([call])
    assert len(records) == 1
    # The llm view's sentinel-resolved field must surface — not the raw "full".
    assert records[0].get("immunogen_sequence") == "(not on file)"
    assert "sequence" not in records[0]


# ---------------------------------------------------------------------------
# (3) Dedup alignment — skipped until Phase 1 step 1
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _LLM_RECORDS_FIELD_PRESENT,
    reason="Phase 1 step 1: pending ToolResult.llm_records field.",
)
def test_dedupe_calls_keeps_llm_records_aligned_with_primary() -> None:
    """``dedupe_calls`` must merge llm_records by the SAME identity that
    collapses primary_records — identity computed on primary, llm view
    rides along by index.
    """
    # Two calls (e.g. cross-group cache reuse) with overlapping records.
    raw_a = [
        {"storage_url": "s3://x/0023.pdf", "title": "PM-LNP-0023 Product Flyer"},
        {"storage_url": "s3://x/dev.pdf",  "title": "Development Flyer"},
    ]
    llm_a = [
        # Hypothetical llm-ready shape — could rename storage_url -> source_uri etc.
        {"source_uri": "s3://x/0023.pdf", "display_title": "PM-LNP-0023 Product Flyer"},
        {"source_uri": "s3://x/dev.pdf",  "display_title": "Development Flyer"},
    ]
    raw_b = [{"storage_url": "s3://x/0023.pdf", "title": "PM-LNP-0023 Product Flyer"}]  # dup of [0]
    llm_b = [{"source_uri": "s3://x/0023.pdf", "display_title": "PM-LNP-0023 Product Flyer"}]

    call_a = _make_call(
        tool_name="document_lookup_tool",
        role="primary",
        primary_records=raw_a,
        llm_records=llm_a,
    )
    call_b = _make_call(
        tool_name="document_lookup_tool",
        role="supporting",
        primary_records=raw_b,
        llm_records=llm_b,
    )

    merged = dedupe_calls([call_a, call_b])
    assert len(merged) == 1
    merged_result = merged[0].result
    assert merged_result is not None

    # Primary records deduped to 2 unique.
    assert len(merged_result.primary_records) == 2
    # llm_records must be the same length and 1:1 aligned with primary.
    assert len(merged_result.llm_records) == 2
    for raw_rec, llm_rec in zip(
        merged_result.primary_records, merged_result.llm_records, strict=True,
    ):
        # Pair-up invariant: same underlying record at same index.
        assert raw_rec["storage_url"] == llm_rec["source_uri"]
