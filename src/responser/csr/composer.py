from __future__ import annotations

from typing import Any, Iterator

from src.responser.csr.draft_llm import generate_draft, stream_draft
from src.responser.csr.extractors import (
    collect_calls_by_bucket,
    collect_routing_notes,
    extract_document_files,
    extract_historical_threads,
    extract_operational_records,
    extract_retrieval_confidence,
    extract_structured_records,
    extract_technical_doc_matches,
    resolve_primary_service_document,
)
from src.responser.csr.grounding import build_trust_signal, filter_historical_threads
from src.responser.csr.sections import (
    format_document_files_section,
    format_documents_section,
    format_draft_section,
    format_operational_section,
    format_routing_section,
    format_service_document_section,
    format_structured_section,
    format_threads_section,
    format_trust_section,
)
from src.responser.models import ComposedResponse, ContentBlock, ResponseInput, ResponsePlan


def _gather_inputs(response_input: ResponseInput) -> dict[str, Any]:
    """One-shot extract: bucket calls, pull every piece of evidence the
    composer needs, and compute the trust signal. Shared by the streaming
    and non-streaming entry points so both see identical data."""
    buckets = collect_calls_by_bucket(response_input)
    raw_historical_threads = extract_historical_threads(buckets["historical"])
    historical_threads = filter_historical_threads(raw_historical_threads)
    document_matches = extract_technical_doc_matches(buckets["technical_docs"])
    document_files = extract_document_files(buckets["document_files"])
    structured_records = extract_structured_records(buckets["structured"])
    operational_records = extract_operational_records(buckets["operational"])
    retrieval_confidence = extract_retrieval_confidence(buckets["technical_docs"])
    routing_notes = collect_routing_notes(response_input)
    primary_service_document, primary_service_document_error = resolve_primary_service_document(
        response_input
    )
    trust_signal = build_trust_signal(
        raw_historical_threads=raw_historical_threads,
        surfaced_historical_threads=historical_threads,
        documents=document_matches,
        retrieval_confidence=retrieval_confidence,
        structured_records=structured_records,
        operational_records=operational_records,
    )
    return {
        "buckets": buckets,
        "raw_historical_threads": raw_historical_threads,
        "historical_threads": historical_threads,
        "document_matches": document_matches,
        "document_files": document_files,
        "structured_records": structured_records,
        "operational_records": operational_records,
        "routing_notes": routing_notes,
        "primary_service_document": primary_service_document,
        "primary_service_document_error": primary_service_document_error,
        "trust_signal": trust_signal,
    }


def _build_panel_section_pairs(inputs: dict[str, Any]) -> list[tuple[str, ContentBlock]]:
    """Build every non-draft, non-trust panel section in display order. Each
    pair is (section_text, ContentBlock) — the text goes into the Slack-style
    message, the block is what the frontend renders. Sections without data
    are omitted (no placeholder noise)."""
    pairs: list[tuple[str, ContentBlock]] = []
    trust_signal = inputs["trust_signal"]
    structured_records = inputs["structured_records"]
    historical_threads = inputs["historical_threads"]
    document_matches = inputs["document_matches"]
    document_files = inputs["document_files"]
    primary_service_document = inputs["primary_service_document"]
    operational_records = inputs["operational_records"]
    routing_notes = inputs["routing_notes"]

    if structured_records:
        section = format_structured_section(structured_records)
        pairs.append((section, ContentBlock(
            block_type="structured_facts",
            title="Live catalog / pricing facts",
            body=section,
            data={"records": structured_records},
        )))

    if historical_threads:
        section = format_threads_section(historical_threads, trust_signal=trust_signal)
        pairs.append((section, ContentBlock(
            block_type="historical_references",
            title="Similar past inquiries",
            body=section,
            data={"threads": historical_threads},
        )))

    if document_matches:
        section = format_documents_section(document_matches, trust_signal=trust_signal)
        pairs.append((section, ContentBlock(
            block_type="relevant_documents",
            title="Relevant documents",
            body=section,
            data={"matches": document_matches},
        )))

    if document_files:
        section = format_document_files_section(document_files)
        pairs.append((section, ContentBlock(
            block_type="document_files",
            title="Matched document files",
            body=section,
            data={"files": document_files},
        )))

    if primary_service_document:
        section = format_service_document_section(primary_service_document)
        pairs.append((section, ContentBlock(
            block_type="service_primary_document",
            title="Primary service document",
            body=section,
            data=primary_service_document,
        )))

    if operational_records:
        section = format_operational_section(operational_records)
        pairs.append((section, ContentBlock(
            block_type="operational_records",
            title="Operational records (QuickBooks)",
            body=section,
            data={"records": operational_records},
        )))

    if routing_notes:
        section = format_routing_section(routing_notes)
        pairs.append((section, ContentBlock(
            block_type="routing_notes",
            title="AI routing notes",
            body=section,
            data={"notes": routing_notes},
        )))

    return pairs


def _build_debug_info(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "csr_mode": True,
        "grounding_status": inputs["trust_signal"]["grounding_status"],
        "historical_threads_returned": len(inputs["historical_threads"]),
        "historical_threads_raw": len(inputs["raw_historical_threads"]),
        "document_matches_returned": len(inputs["document_matches"]),
        "document_files_returned": len(inputs["document_files"]),
        "primary_service_document_found": bool(inputs["primary_service_document"]),
        "primary_service_document_error": inputs["primary_service_document_error"],
        "structured_records_returned": len(inputs["structured_records"]),
        "operational_records_returned": len(inputs["operational_records"]),
        "unrouted_tool_calls": [call.tool_name for call in inputs["buckets"]["unknown"]],
        "retrieval_quality_tier": inputs["trust_signal"]["retrieval_quality_tier"],
    }


def _assemble_composed_response(
    *,
    inputs: dict[str, Any],
    draft_text: str,
    panel_pairs: list[tuple[str, ContentBlock]],
) -> ComposedResponse:
    """Combine draft + trust + panel sections into the canonical response.

    Section ordering: draft first (most important), trust signal second
    (grounding badge), then panels in evidence order. Every reply needs the
    draft and grounding badge; everything else is data-gated.
    """
    trust_signal = inputs["trust_signal"]
    sections: list[str] = [
        format_draft_section(draft_text),
        format_trust_section(trust_signal),
    ]
    content_blocks: list[ContentBlock] = [
        ContentBlock(
            block_type="csr_draft",
            title="Draft reply for CSR",
            body=draft_text,
            data={
                "grounding_status": trust_signal["grounding_status"],
                "historical_thread_count": len(inputs["historical_threads"]),
                "document_count": len(inputs["document_matches"]),
                "structured_record_count": len(inputs["structured_records"]),
                "operational_record_count": len(inputs["operational_records"]),
                "routing_note_count": len(inputs["routing_notes"]),
            },
        ),
        ContentBlock(
            block_type="trust_signal",
            title="Grounding and retrieval quality",
            body=trust_signal["summary"],
            data=trust_signal,
        ),
    ]
    for section_text, block in panel_pairs:
        sections.append(section_text)
        content_blocks.append(block)

    return ComposedResponse(
        message="\n\n".join(sections),
        response_type="csr_draft",
        content_blocks=content_blocks,
        debug_info=_build_debug_info(inputs),
    )


def render_csr_draft_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    inputs = _gather_inputs(response_input)
    draft_text = generate_draft(
        query=response_input.query,
        asked_focus=response_input.asked_focus,
        threads=inputs["historical_threads"],
        documents=inputs["document_matches"],
        structured_records=inputs["structured_records"],
        operational_records=inputs["operational_records"],
        trust_signal=inputs["trust_signal"],
        primary_service_document=inputs["primary_service_document"],
    )
    panel_pairs = _build_panel_section_pairs(inputs)
    return _assemble_composed_response(
        inputs=inputs,
        draft_text=draft_text,
        panel_pairs=panel_pairs,
    )


def stream_csr_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> Iterator[tuple[str, Any]]:
    """Yield composer events in display order: trust signal, every populated
    panel section, draft start/chunks/end, then a final ``composed`` event
    carrying the fully assembled :class:`ComposedResponse`.

    Event tuples are ``(event_name, payload)``. Panel sections are emitted
    before draft generation so the UI fills in all the deterministic
    evidence while the LLM is still working on the reply.
    """
    inputs = _gather_inputs(response_input)

    yield "trust", inputs["trust_signal"]

    panel_pairs = _build_panel_section_pairs(inputs)
    for _section_text, block in panel_pairs:
        yield "section", block

    yield "draft_start", {}
    chunks: list[str] = []
    for chunk in stream_draft(
        query=response_input.query,
        asked_focus=response_input.asked_focus,
        threads=inputs["historical_threads"],
        documents=inputs["document_matches"],
        structured_records=inputs["structured_records"],
        operational_records=inputs["operational_records"],
        trust_signal=inputs["trust_signal"],
        primary_service_document=inputs["primary_service_document"],
    ):
        chunks.append(chunk)
        yield "draft_chunk", {"text": chunk}
    draft_text = "".join(chunks).strip()
    yield "draft_end", {"draft": draft_text}

    composed = _assemble_composed_response(
        inputs=inputs,
        draft_text=draft_text,
        panel_pairs=panel_pairs,
    )
    yield "composed", composed
