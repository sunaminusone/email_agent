"""CSR-mode renderer: produces a draft reply + reference cards for the rep.

This is the only renderer used in CSR mode (see _render_response dispatch
in src/responser/service.py). Output structure:

    DRAFT
        LLM-synthesized draft grounded in every dispatched tool's output.
    LIVE STRUCTURED FACTS
        Catalog / pricing records from postgres (when those tools fired).
    SIMILAR PAST INQUIRIES
        Top historical threads from the HubSpot corpus.
    RELEVANT DOCUMENTS
        Top KB chunks from technical RAG (and matched document files).
    OPERATIONAL RECORDS
        QuickBooks records (orders / invoices / shipping / customer)
        when the corresponding tools fire.
    AI ROUTING NOTES (only present when routing flagged clarify/handoff)
        Surfaces the original routing judgment so the rep is aware
        without being blocked.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from src.common.execution_models import ExecutedToolCall
from src.config import get_llm
from src.services.service_documents import get_primary_service_document_link
from src.responser.models import ComposedResponse, ContentBlock, ResponseInput, ResponsePlan

_HISTORICAL_STRONG_MATCH = 0.75
_HISTORICAL_USABLE_MATCH = 0.55

# Maps tool_name → rendering bucket. The renderer routes each ExecutedToolCall
# to its bucket and then to a bucket-specific formatter. New tools must be
# added here explicitly; unknown tools fall into "unknown" and are logged
# under debug_info but not surfaced (defensive default — never crash on a
# tool the renderer hasn't been taught about).
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


_DRAFT_SYSTEM_PROMPT = """\
You are drafting a customer-service reply for a customer-service representative
(CSR) at ProMab Biotechnologies. The CSR will review and edit your draft
before sending — your job is to give them a strong starting point.

Inputs you will see:
1. The new customer inquiry.
2. STRUCTURED LIVE FACTS — catalog / pricing records from our live database
   (only present when the corresponding tools fired and returned matches).
3. Past similar inquiries with how our sales team replied to them.
4. Relevant documentation chunks from our knowledge base.
5. OPERATIONAL RECORDS — order / invoice / shipping / customer data from
   QuickBooks (only present when those tools fired).

Rules:
- Write a clear, professional draft reply addressed to the new customer.
- STRUCTURED LIVE FACTS are AUTHORITATIVE. When live catalog / pricing
  records are present, cite catalog_no, price, currency, and lead_time
  EXACTLY as given — do NOT round, paraphrase, or pull these numbers from
  past sales emails (which may be outdated). If past sales emails contradict
  the live data, trust the live data and ignore the email's number.
- OPERATIONAL RECORDS (orders / invoices / shipping) are also authoritative —
  cite order numbers, statuses, and tracking IDs exactly as given.
- Lean on past sales replies for TONE and STRUCTURE — how our team talks to
  customers — but not for specific numbers when live data exists.
- Use documentation chunks to cite technical specs and process details only
  when they appear in the inputs. Never invent numbers, catalog IDs, or
  commitments.
- If the question is ambiguous or you would need more info to answer well,
  draft a brief reply that asks the customer for the specific missing detail
  rather than guessing.
- Reply in the same language as the customer inquiry (English by default).
- Do NOT add headers like "Draft:" — the wrapper takes care of that.
- Keep it concise; the CSR will expand if needed.
"""


class _DraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: str = ""


def render_csr_draft_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    buckets = _collect_calls_by_bucket(response_input)

    raw_historical_threads = _extract_historical_threads(buckets["historical"])
    historical_threads = _filter_historical_threads(raw_historical_threads)
    document_matches = _extract_technical_doc_matches(buckets["technical_docs"])
    document_files = _extract_document_files(buckets["document_files"])
    structured_records = _extract_structured_records(buckets["structured"])
    operational_records = _extract_operational_records(buckets["operational"])
    retrieval_confidence = _extract_retrieval_confidence(buckets["technical_docs"])
    routing_notes = _collect_routing_notes(response_input)
    primary_service_document, primary_service_document_error = _resolve_primary_service_document(
        response_input
    )

    trust_signal = _build_trust_signal(
        raw_historical_threads=raw_historical_threads,
        surfaced_historical_threads=historical_threads,
        documents=document_matches,
        retrieval_confidence=retrieval_confidence,
        structured_records=structured_records,
        operational_records=operational_records,
    )

    draft_text = _generate_draft(
        query=response_input.query,
        threads=historical_threads,
        documents=document_matches,
        structured_records=structured_records,
        operational_records=operational_records,
        trust_signal=trust_signal,
        primary_service_document=primary_service_document,
    )

    sections: list[str] = []
    sections.append(_format_draft_section(draft_text))
    sections.append(_format_trust_section(trust_signal))
    if structured_records:
        sections.append(_format_structured_section(structured_records))
    sections.append(_format_threads_section(historical_threads, trust_signal=trust_signal))
    sections.append(_format_documents_section(document_matches, trust_signal=trust_signal))
    if document_files:
        sections.append(_format_document_files_section(document_files))
    if primary_service_document:
        sections.append(_format_service_document_section(primary_service_document))
    if operational_records:
        sections.append(_format_operational_section(operational_records))
    if routing_notes:
        sections.append(_format_routing_section(routing_notes))

    message = "\n\n".join(sections)

    content_blocks = [
        ContentBlock(
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
        ),
        ContentBlock(
            block_type="trust_signal",
            title="Grounding and retrieval quality",
            body=trust_signal["summary"],
            data=trust_signal,
        ),
    ]
    if structured_records:
        content_blocks.append(
            ContentBlock(
                block_type="structured_facts",
                title="Live catalog / pricing facts",
                body=_format_structured_section(structured_records),
                data={"records": structured_records},
            )
        )
    if historical_threads:
        content_blocks.append(
            ContentBlock(
                block_type="historical_references",
                title="Similar past inquiries",
                body=_format_threads_section(historical_threads, trust_signal=trust_signal),
                data={"threads": historical_threads},
            )
        )
    if document_matches:
        content_blocks.append(
            ContentBlock(
                block_type="relevant_documents",
                title="Relevant documents",
                body=_format_documents_section(document_matches, trust_signal=trust_signal),
                data={"matches": document_matches},
            )
        )
    if document_files:
        content_blocks.append(
            ContentBlock(
                block_type="document_files",
                title="Matched document files",
                body=_format_document_files_section(document_files),
                data={"files": document_files},
            )
        )
    if primary_service_document:
        content_blocks.append(
            ContentBlock(
                block_type="service_primary_document",
                title="Primary service document",
                body=_format_service_document_section(primary_service_document),
                data=primary_service_document,
            )
        )
    if operational_records:
        content_blocks.append(
            ContentBlock(
                block_type="operational_records",
                title="Operational records (QuickBooks)",
                body=_format_operational_section(operational_records),
                data={"records": operational_records},
            )
        )
    if routing_notes:
        content_blocks.append(
            ContentBlock(
                block_type="routing_notes",
                title="AI routing notes",
                body=_format_routing_section(routing_notes),
                data={"notes": routing_notes},
            )
        )

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


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------


def _collect_calls_by_bucket(
    response_input: ResponseInput,
) -> dict[str, list[ExecutedToolCall]]:
    """Iterate every executed tool call once and bucket by tool_name.

    Tools not in _TOOL_BUCKETS land in "unknown" and are surfaced in
    debug_info so a missing renderer wiring is observable rather than silent.
    """
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


def _extract_historical_threads(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    for call in calls:
        threads = (call.result.structured_facts or {}).get("threads") or []
        if isinstance(threads, list) and threads:
            return threads
    return []


def _extract_technical_doc_matches(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    for call in calls:
        matches = (call.result.structured_facts or {}).get("matches") or []
        if isinstance(matches, list) and matches:
            return matches[:5]
    return []


def _extract_retrieval_confidence(calls: list[ExecutedToolCall]) -> dict[str, Any]:
    for call in calls:
        confidence = (call.result.structured_facts or {}).get("retrieval_confidence") or {}
        if isinstance(confidence, dict) and confidence:
            return confidence
    return {}


def _extract_document_files(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    """Flatten document_lookup_tool matches across calls (rare in practice)."""
    out: list[dict[str, Any]] = []
    for call in calls:
        matches = call.result.primary_records or []
        for match in matches:
            if isinstance(match, dict):
                out.append(match)
    return out[:5]


def _extract_structured_records(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    """Flatten catalog / pricing records across all structured-bucket calls.

    Each record is annotated with `_source_tool` so downstream formatters
    and the LLM prompt can show which tool produced it. Reads
    `pricing_records` first (pricing_lookup_tool's specific key), then
    falls back to `primary_records` (catalog_lookup_tool, generic).
    """
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


def _extract_operational_records(calls: list[ExecutedToolCall]) -> list[dict[str, Any]]:
    """Flatten QuickBooks records (orders / invoices / shipping / customer).

    Demo phase de-prioritizes these tools (they rarely fire), but the
    renderer surfaces them when present so any future routing wiring is
    immediately visible.
    """
    out: list[dict[str, Any]] = []
    for call in calls:
        records = call.result.primary_records or []
        for record in records:
            if not isinstance(record, dict):
                continue
            annotated = dict(record)
            annotated["_source_tool"] = call.tool_name
            out.append(annotated)
    return out[:8]


def _collect_routing_notes(response_input: ResponseInput) -> list[str]:
    notes: list[str] = []
    for outcome in response_input.group_outcomes:
        rd = getattr(outcome, "route_decision", None)
        if rd is None:
            continue
        reason = getattr(rd, "reason", "") or ""
        if reason.startswith("AI_ROUTING_NOTE"):
            notes.append(reason)
    return notes


def _requests_documentation(response_input: ResponseInput) -> bool:
    demand_profile = response_input.demand_profile
    if demand_profile is not None and "needs_documentation" in demand_profile.active_request_flags:
        return True
    for outcome in response_input.group_outcomes:
        scoped_demand = getattr(outcome, "scoped_demand", None)
        if scoped_demand is not None and "needs_documentation" in getattr(scoped_demand, "request_flags", []):
            return True
    return False


def _resolved_service_name(response_input: ResponseInput) -> str:
    resolved = response_input.resolved_object_state
    if resolved is None:
        return ""
    for candidate in (
        resolved.primary_object,
        resolved.active_object,
        *resolved.secondary_objects,
    ):
        if candidate is not None and candidate.object_type == "service":
            return str(
                candidate.display_name
                or candidate.canonical_value
                or candidate.identifier
                or ""
            ).strip()
    return ""


def _resolve_primary_service_document(
    response_input: ResponseInput,
) -> tuple[dict[str, Any] | None, str]:
    if not _requests_documentation(response_input):
        return None, ""
    service_name = _resolved_service_name(response_input)
    if not service_name:
        return None, ""
    try:
        return get_primary_service_document_link(service_name), ""
    except Exception as exc:
        return None, str(exc)


def _filter_historical_threads(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not threads:
        return []
    strong = [t for t in threads if float(t.get("best_score", 0.0) or 0.0) >= _HISTORICAL_STRONG_MATCH]
    if strong:
        return strong[:3]
    usable = [t for t in threads if float(t.get("best_score", 0.0) or 0.0) >= _HISTORICAL_USABLE_MATCH]
    return usable[:2]


def _build_trust_signal(
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

    # Live structured/operational data is authoritative; if present, the
    # draft is grounded regardless of historical strength.
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


# ---------------------------------------------------------------------------
# LLM draft generation
# ---------------------------------------------------------------------------


def _generate_draft(
    *,
    query: str,
    threads: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    structured_records: list[dict[str, Any]],
    operational_records: list[dict[str, Any]],
    trust_signal: dict[str, Any],
    primary_service_document: dict[str, Any] | None,
) -> str:
    if not query.strip():
        return ""

    parts: list[str] = []
    parts.append(f"NEW CUSTOMER INQUIRY:\n{query}\n")

    if structured_records:
        parts.append(
            "\nSTRUCTURED LIVE FACTS (catalog / pricing — AUTHORITATIVE, prefer over past emails):"
        )
        for i, record in enumerate(structured_records, 1):
            source = record.get("_source_tool") or "unknown_tool"
            parts.append(
                f"\n--- record {i} from {source} ---\n{_render_record_for_llm(record)}"
            )
    else:
        parts.append("\nSTRUCTURED LIVE FACTS: (none — no live catalog/pricing tool fired or returned matches)")

    if threads:
        parts.append("\nPAST SIMILAR INQUIRIES (with our sales replies — for tone/structure, NOT for live numbers):")
        for i, t in enumerate(threads, 1):
            units = t.get("units") or []
            if not units:
                continue
            first = units[0]
            inst = first.get("institution") or "unknown"
            service = first.get("service_of_interest") or ""
            parts.append(f"\n--- past inquiry {i} ({inst}, service={service or 'n/a'}) ---")
            for u in units:
                parts.append(u.get("page_content", ""))
    else:
        parts.append("\nPAST SIMILAR INQUIRIES: (none retrieved)")

    if documents:
        parts.append("\nRELEVANT DOCUMENTATION CHUNKS:")
        for i, m in enumerate(documents, 1):
            section = m.get("section_type") or "unknown"
            preview = (m.get("content_preview") or "")[:600]
            parts.append(f"\n--- doc {i} (section={section}) ---\n{preview}")
    else:
        parts.append("\nRELEVANT DOCUMENTATION CHUNKS: (none retrieved)")

    if primary_service_document:
        parts.append("\nPRIMARY SERVICE DOCUMENT AVAILABLE:")
        parts.append(
            _render_record_for_llm(
                {
                    "title": primary_service_document.get("title", ""),
                    "document_type": primary_service_document.get("document_type", ""),
                    "file_name": primary_service_document.get("file_name", ""),
                    "presigned_url": primary_service_document.get("presigned_url", ""),
                }
            )
        )
    else:
        parts.append("\nPRIMARY SERVICE DOCUMENT AVAILABLE: (none)")

    if operational_records:
        parts.append(
            "\nOPERATIONAL RECORDS (orders / invoices / shipping / customer — AUTHORITATIVE):"
        )
        for i, record in enumerate(operational_records, 1):
            source = record.get("_source_tool") or "unknown_tool"
            parts.append(
                f"\n--- record {i} from {source} ---\n{_render_record_for_llm(record)}"
            )

    parts.append(
        "\nGROUNDING STATUS:\n"
        f"- grounding_status: {trust_signal.get('grounding_status', 'unknown')}\n"
        f"- retrieval_quality_tier: {trust_signal.get('retrieval_quality_tier', 'unknown')}\n"
        f"- has_live_data: {trust_signal.get('has_live_data', False)}\n"
        f"- trust_summary: {trust_signal.get('summary', '')}\n"
    )

    user_prompt = "\n".join(parts)

    try:
        llm = get_llm().with_structured_output(_DraftOutput)
        system_prompt = _DRAFT_SYSTEM_PROMPT
        if trust_signal.get("grounding_status") == "ungrounded":
            system_prompt += """

Additional rule for this turn:
- No strong historical or documentation evidence was retrieved.
- Draft a cautious intake-style reply that asks only for the minimum missing
  details needed to move forward.
- Do not imply that a specific service, price, lead time, or technical path
  is confirmed unless it appears in the inputs above.
"""
        elif trust_signal.get("grounding_status") == "weakly_grounded":
            system_prompt += """

Additional rule for this turn:
- Evidence is partial or weak.
- You may borrow tone and structure from retrieved material, but avoid
  overcommitting on specific technical or commercial details unless they are
  explicitly present in the inputs.
"""
        if primary_service_document:
            system_prompt += """

Also for this turn:
- A primary service document link is available.
- If the customer is asking for documentation, naturally mention that the flyer/brochure/report is attached or included via link.
- Do not paste raw long URLs into the prose unless necessary; refer to it as the attached or linked document.
"""
        result = llm.invoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        return str(getattr(result, "draft", "") or "").strip()
    except Exception as exc:
        return f"[Draft generation failed: {exc}. CSR: please draft manually using the references below.]"


# ---------------------------------------------------------------------------
# Formatting (Slack-style)
# ---------------------------------------------------------------------------


def _format_draft_section(draft: str) -> str:
    if not draft:
        return "*📝 Draft reply*\n_(no draft generated — see references below)_"
    return f"*📝 Draft reply* _(CSR: please review & edit before sending)_\n\n{draft}"


def _format_trust_section(trust_signal: dict[str, Any]) -> str:
    lines = ["*🧭 Grounding signal*"]
    lines.append(f"   • status: `{trust_signal.get('grounding_status', 'unknown')}`")
    lines.append(f"   • retrieval quality: `{trust_signal.get('retrieval_quality_tier', 'unknown')}`")
    lines.append(f"   • {trust_signal.get('summary', '')}")
    return "\n".join(lines)


def _format_threads_section(threads: list[dict[str, Any]], *, trust_signal: dict[str, Any]) -> str:
    lines = ["*📚 Similar past inquiries*"]
    if not threads:
        lines.append("   • No strong similar historical replies were retrieved for this draft.")
        if trust_signal.get("historical_threads_raw", 0):
            lines.append(
                f"   • Raw retrieval found {trust_signal['historical_threads_raw']} candidate thread(s), "
                "but none passed the surfacing threshold."
            )
        return "\n".join(lines)
    for i, t in enumerate(threads, 1):
        units = t.get("units") or []
        if not units:
            continue
        first = units[0]
        date = (first.get("submitted_at") or "")[:10]
        inst = first.get("institution") or "unknown institution"
        sender = first.get("sender_name") or "unknown sender"
        service = first.get("service_of_interest") or "—"
        product = first.get("products_of_interest") or "—"
        score = t.get("best_score", 0.0)

        lines.append(f"\n*[{i}]* `{date}` *{sender}* ({inst}) — score `{score:.2f}`")
        lines.append(f"   service: `{service}` · product: `{product}` · {len(units)} reply unit(s)")

        # Compress the units into one block
        for j, u in enumerate(units, 1):
            content = (u.get("page_content") or "").strip()
            if not content:
                continue
            label = f"reply {j}/{len(units)}"
            lines.append(f"\n   _{label}_")
            for line in content.splitlines():
                lines.append(f"   > {line}")
            attachments = u.get("attachments") or []
            if attachments:
                lines.append(_format_attachments_line(attachments))
    return "\n".join(lines)


def _format_attachments_line(attachments: list[dict[str, Any]]) -> str:
    """Render one inline 📎 line listing the files exchanged in a reply unit."""
    parts: list[str] = []
    for att in attachments:
        name = att.get("name") or att.get("id") or "file"
        ext = att.get("extension") or ""
        url = att.get("url") or ""
        label = f"{name}.{ext}" if ext and not str(name).lower().endswith(f".{ext.lower()}") else name
        parts.append(f"<{url}|{label}>" if url else label)
    return "   📎 " + " · ".join(parts)


def _format_documents_section(matches: list[dict[str, Any]], *, trust_signal: dict[str, Any]) -> str:
    lines = ["*📄 Relevant documents*"]
    if not matches:
        lines.append("   • No relevant documentation chunks were retrieved for this draft.")
        return "\n".join(lines)
    for i, m in enumerate(matches, 1):
        section = m.get("section_type") or "unknown"
        chunk_label = m.get("chunk_label") or m.get("file_name") or ""
        score = m.get("final_score") or m.get("base_score") or 0.0
        preview = (m.get("content_preview") or "").strip()
        title = chunk_label or section
        lines.append(f"\n*[{i}]* `{section}` — {title} — score `{score:.2f}`")
        if preview:
            for line in preview.splitlines()[:6]:
                lines.append(f"   > {line}")
    return "\n".join(lines)


def _format_routing_section(notes: list[str]) -> str:
    lines = ["*⚠️ AI routing notes* _(the agent flagged these — judgment call for the CSR)_"]
    for note in notes:
        lines.append(f"   • {note}")
    return "\n".join(lines)


_STRUCTURED_DISPLAY_FIELDS = (
    "catalog_no",
    "name",
    "display_name",
    "price",
    "price_text",
    "currency",
    "lead_time",
    "lead_time_text",
    "size",
    "format",
    "unit",
    "business_line",
    "target_antigen",
    "species_reactivity_text",
    "application_text",
)


def _format_structured_section(records: list[dict[str, Any]]) -> str:
    lines = ["*💰 Live catalog / pricing facts* _(from postgres — authoritative)_"]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        source = str(record.get("_source_tool") or "unknown_tool")
        by_source.setdefault(source, []).append(record)

    for source, group in by_source.items():
        lines.append(f"\n   _from {source}:_")
        for i, record in enumerate(group, 1):
            label = (
                record.get("display_name")
                or record.get("name")
                or record.get("catalog_no")
                or f"record {i}"
            )
            lines.append(f"\n   *[{i}]* {label}")
            for field in _STRUCTURED_DISPLAY_FIELDS:
                if field in {"display_name", "name"}:
                    continue
                value = record.get(field)
                if value in (None, "", []):
                    continue
                lines.append(f"      • {field}: `{value}`")
    return "\n".join(lines)


def _format_document_files_section(files: list[dict[str, Any]]) -> str:
    lines = ["*📁 Matched document files*"]
    for i, f in enumerate(files, 1):
        title = (
            f.get("document_name")
            or f.get("file_name")
            or f.get("path")
            or f.get("source_path")
            or f"file {i}"
        )
        doc_type = f.get("document_type") or ""
        path = f.get("path") or f.get("source_path") or ""
        suffix = f" ({doc_type})" if doc_type else ""
        lines.append(f"   *[{i}]* {title}{suffix}")
        if path:
            lines.append(f"      • path: `{path}`")
    return "\n".join(lines)


def _format_service_document_section(document: dict[str, Any]) -> str:
    title = str(document.get("title") or document.get("file_name") or "Primary service document").strip()
    file_name = str(document.get("file_name") or "").strip()
    document_type = str(document.get("document_type") or "").strip()
    presigned_url = str(document.get("presigned_url") or "").strip()
    storage_url = str(document.get("storage_url") or "").strip()

    lines = ["*🔗 Primary service document*"]
    suffix = f" ({document_type})" if document_type else ""
    lines.append(f"   • title: `{title}`{suffix}")
    if file_name:
        lines.append(f"   • file: `{file_name}`")
    if presigned_url:
        lines.append(f"   • temporary link: `{presigned_url}`")
    elif storage_url:
        lines.append(f"   • storage: `{storage_url}`")
    return "\n".join(lines)


def _format_operational_section(records: list[dict[str, Any]]) -> str:
    lines = ["*📋 Operational records (QuickBooks)* _(authoritative — order / invoice / shipping)_"]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        source = str(record.get("_source_tool") or "unknown_tool")
        by_source.setdefault(source, []).append(record)

    for source, group in by_source.items():
        lines.append(f"\n   _from {source}:_")
        for i, record in enumerate(group, 1):
            label = (
                record.get("name")
                or record.get("display_name")
                or record.get("order_number")
                or record.get("invoice_number")
                or record.get("tracking_number")
                or f"record {i}"
            )
            lines.append(f"   *[{i}]* {label}")
            for key, value in record.items():
                if key.startswith("_"):
                    continue
                if value in (None, "", [], {}):
                    continue
                lines.append(f"      • {key}: `{value}`")
    return "\n".join(lines)


def _render_record_for_llm(record: dict[str, Any]) -> str:
    """Render a structured record as `key: value` lines for LLM consumption."""
    lines: list[str] = []
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if value in (None, "", [], {}):
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
