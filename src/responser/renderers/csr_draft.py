"""CSR-mode renderer: produces a draft reply + reference cards for the rep.

This is the only renderer used in CSR mode (see _render_response dispatch
in src/responser/service.py). Output structure:

    DRAFT
        LLM-synthesized draft based on retrieved historical replies + docs.
    SIMILAR PAST INQUIRIES
        Top historical threads from the HubSpot corpus, with the customer
        message and the actual sales reply for each one.
    RELEVANT DOCUMENTS
        Top KB chunks from the technical RAG.
    AI ROUTING NOTES (only present when routing flagged clarify/handoff)
        Surfaces the original routing judgment so the rep is aware
        without being blocked.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from src.config import get_llm
from src.responser.models import ComposedResponse, ContentBlock, ResponseInput, ResponsePlan

_HISTORICAL_STRONG_MATCH = 0.75
_HISTORICAL_USABLE_MATCH = 0.55


_DRAFT_SYSTEM_PROMPT = """\
You are drafting a customer-service reply for a customer-service representative
(CSR) at ProMab Biotechnologies. The CSR will review and edit your draft
before sending — your job is to give them a strong starting point.

Inputs you will see:
1. The new customer inquiry.
2. Past similar inquiries with how our sales team replied to them.
3. Relevant documentation chunks from our knowledge base.

Rules:
- Write a clear, professional draft reply addressed to the new customer.
- Lean heavily on the language and structure of past sales replies — that is
  how our team actually talks to customers.
- Use the documentation chunks to cite specific facts (timelines, prices,
  technical specs) only when they are present in the inputs. Never invent
  numbers, catalog IDs, or commitments.
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
    raw_historical_threads = _collect_historical_threads(response_input)
    historical_threads = _filter_historical_threads(raw_historical_threads)
    document_matches = _collect_document_matches(response_input)
    retrieval_confidence = _collect_retrieval_confidence(response_input)
    routing_notes = _collect_routing_notes(response_input)
    trust_signal = _build_trust_signal(
        raw_historical_threads=raw_historical_threads,
        surfaced_historical_threads=historical_threads,
        documents=document_matches,
        retrieval_confidence=retrieval_confidence,
    )

    draft_text = _generate_draft(
        query=response_input.query,
        threads=historical_threads,
        documents=document_matches,
        trust_signal=trust_signal,
    )

    sections: list[str] = []
    sections.append(_format_draft_section(draft_text))
    sections.append(_format_trust_section(trust_signal))
    sections.append(_format_threads_section(historical_threads, trust_signal=trust_signal))
    sections.append(_format_documents_section(document_matches, trust_signal=trust_signal))
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
            "retrieval_quality_tier": trust_signal["retrieval_quality_tier"],
        },
    )


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------


def _collect_historical_threads(response_input: ResponseInput) -> list[dict[str, Any]]:
    for call in response_input.execution_result.executed_calls:
        if call.tool_name != "historical_thread_tool" or call.result is None:
            continue
        threads = call.result.structured_facts.get("threads") or []
        if isinstance(threads, list):
            return threads
    return []


def _collect_document_matches(response_input: ResponseInput) -> list[dict[str, Any]]:
    for call in response_input.execution_result.executed_calls:
        if call.tool_name != "technical_rag_tool" or call.result is None:
            continue
        matches = call.result.structured_facts.get("matches") or []
        if isinstance(matches, list):
            return matches[:5]
    return []


def _collect_retrieval_confidence(response_input: ResponseInput) -> dict[str, Any]:
    for call in response_input.execution_result.executed_calls:
        if call.tool_name != "technical_rag_tool" or call.result is None:
            continue
        confidence = call.result.structured_facts.get("retrieval_confidence") or {}
        if isinstance(confidence, dict):
            return confidence
    return {}


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

    if surfaced_historical_threads and retrieval_quality_tier == "high":
        grounding_status = "grounded"
    elif surfaced_historical_threads or documents:
        grounding_status = "weakly_grounded"
    else:
        grounding_status = "ungrounded"

    if grounding_status == "grounded":
        summary = (
            f"Based on {len(surfaced_historical_threads)} strong similar historical thread(s) "
            f"and {len(documents)} document match(es)."
        )
    elif grounding_status == "weakly_grounded":
        summary = (
            f"Partial evidence only: {len(surfaced_historical_threads)} usable historical thread(s) "
            f"and {len(documents)} document match(es). CSR should verify details before sending."
        )
    else:
        summary = (
            "No strong historical replies or relevant documents were retrieved. "
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
    }


# ---------------------------------------------------------------------------
# LLM draft generation
# ---------------------------------------------------------------------------


def _generate_draft(
    *,
    query: str,
    threads: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    trust_signal: dict[str, Any],
) -> str:
    if not query.strip():
        return ""

    parts: list[str] = []
    parts.append(f"NEW CUSTOMER INQUIRY:\n{query}\n")

    if threads:
        parts.append("\nPAST SIMILAR INQUIRIES (with our sales replies):")
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

    parts.append(
        "\nGROUNDING STATUS:\n"
        f"- grounding_status: {trust_signal.get('grounding_status', 'unknown')}\n"
        f"- retrieval_quality_tier: {trust_signal.get('retrieval_quality_tier', 'unknown')}\n"
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
