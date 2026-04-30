from __future__ import annotations

from src.responser.csr.draft_llm import generate_draft
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


def render_csr_draft_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
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

    draft_text = generate_draft(
        query=response_input.query,
        threads=historical_threads,
        documents=document_matches,
        structured_records=structured_records,
        operational_records=operational_records,
        trust_signal=trust_signal,
        primary_service_document=primary_service_document,
    )

    # Each block_type owns one contiguous region: render its section text
    # and append the matching ContentBlock side-by-side. Blocks above the
    # next blank line always render; blocks below render only when their
    # source data is non-empty. The threads/documents pair is asymmetric:
    # the section is always emitted (formatter prints a "no matches" line),
    # but the ContentBlock is skipped when the underlying list is empty.
    sections: list[str] = []
    content_blocks: list[ContentBlock] = []

    sections.append(format_draft_section(draft_text))
    content_blocks.append(ContentBlock(
        block_type="csr_draft",
        title="Draft reply for CSR",
        body=draft_text,
        data={
            "grounding_status": trust_signal["grounding_status"],
            "historical_thread_count": len(historical_threads),
            "document_count": len(document_matches),
            "structured_record_count": len(structured_records),
            "operational_record_count": len(operational_records),
            "routing_note_count": len(routing_notes),
        },
    ))

    sections.append(format_trust_section(trust_signal))
    content_blocks.append(ContentBlock(
        block_type="trust_signal",
        title="Grounding and retrieval quality",
        body=trust_signal["summary"],
        data=trust_signal,
    ))

    if structured_records:
        section = format_structured_section(structured_records)
        sections.append(section)
        content_blocks.append(ContentBlock(
            block_type="structured_facts",
            title="Live catalog / pricing facts",
            body=section,
            data={"records": structured_records},
        ))

    threads_section = format_threads_section(historical_threads, trust_signal=trust_signal)
    sections.append(threads_section)
    if historical_threads:
        content_blocks.append(ContentBlock(
            block_type="historical_references",
            title="Similar past inquiries",
            body=threads_section,
            data={"threads": historical_threads},
        ))

    documents_section = format_documents_section(document_matches, trust_signal=trust_signal)
    sections.append(documents_section)
    if document_matches:
        content_blocks.append(ContentBlock(
            block_type="relevant_documents",
            title="Relevant documents",
            body=documents_section,
            data={"matches": document_matches},
        ))

    if document_files:
        section = format_document_files_section(document_files)
        sections.append(section)
        content_blocks.append(ContentBlock(
            block_type="document_files",
            title="Matched document files",
            body=section,
            data={"files": document_files},
        ))

    if primary_service_document:
        section = format_service_document_section(primary_service_document)
        sections.append(section)
        content_blocks.append(ContentBlock(
            block_type="service_primary_document",
            title="Primary service document",
            body=section,
            data=primary_service_document,
        ))

    if operational_records:
        section = format_operational_section(operational_records)
        sections.append(section)
        content_blocks.append(ContentBlock(
            block_type="operational_records",
            title="Operational records (QuickBooks)",
            body=section,
            data={"records": operational_records},
        ))

    if routing_notes:
        section = format_routing_section(routing_notes)
        sections.append(section)
        content_blocks.append(ContentBlock(
            block_type="routing_notes",
            title="AI routing notes",
            body=section,
            data={"notes": routing_notes},
        ))

    message = "\n\n".join(sections)

    return ComposedResponse(
        message=message,
        response_type="csr_draft",
        content_blocks=content_blocks,
        debug_info={
            "csr_mode": True,
            "grounding_status": trust_signal["grounding_status"],
            "historical_threads_returned": len(historical_threads),
            "historical_threads_raw": len(raw_historical_threads),
            "document_matches_returned": len(document_matches),
            "document_files_returned": len(document_files),
            "primary_service_document_found": bool(primary_service_document),
            "primary_service_document_error": primary_service_document_error,
            "structured_records_returned": len(structured_records),
            "operational_records_returned": len(operational_records),
            "unrouted_tool_calls": [
                call.tool_name for call in buckets["unknown"]
            ],
            "retrieval_quality_tier": trust_signal["retrieval_quality_tier"],
        },
    )
