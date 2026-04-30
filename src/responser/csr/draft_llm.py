from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from src.config import get_llm

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


_UNGROUNDED_RULE = """

Additional rule for this turn:
- No strong historical or documentation evidence was retrieved.
- Draft a cautious intake-style reply that asks only for the minimum missing
  details needed to move forward.
- Do not imply that a specific service, price, lead time, or technical path
  is confirmed unless it appears in the inputs above.
"""

_WEAKLY_GROUNDED_RULE = """

Additional rule for this turn:
- Evidence is partial or weak.
- You may borrow tone and structure from retrieved material, but avoid
  overcommitting on specific technical or commercial details unless they are
  explicitly present in the inputs.
"""

_PRIMARY_DOCUMENT_RULE = """

Also for this turn:
- A primary service document link is available.
- If the customer is asking for documentation, naturally mention that the flyer/brochure/report is attached or included via link.
- Do not paste raw long URLs into the prose unless necessary; refer to it as the attached or linked document.
"""


def _build_system_prompt(
    *,
    grounding_status: str,
    primary_service_document: dict[str, Any] | None,
) -> str:
    prompt = _DRAFT_SYSTEM_PROMPT
    if grounding_status == "ungrounded":
        prompt += _UNGROUNDED_RULE
    elif grounding_status == "weakly_grounded":
        prompt += _WEAKLY_GROUNDED_RULE
    if primary_service_document:
        prompt += _PRIMARY_DOCUMENT_RULE
    return prompt


class DraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: str = ""


def generate_draft(
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
                f"\n--- record {i} from {source} ---\n{render_record_for_llm(record)}"
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
            render_record_for_llm(
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
                f"\n--- record {i} from {source} ---\n{render_record_for_llm(record)}"
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
        llm = get_llm().with_structured_output(DraftOutput)
        system_prompt = _build_system_prompt(
            grounding_status=str(trust_signal.get("grounding_status") or ""),
            primary_service_document=primary_service_document,
        )
        result = llm.invoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        return str(getattr(result, "draft", "") or "").strip()
    except Exception as exc:
        return f"[Draft generation failed: {exc}. CSR: please draft manually using the references below.]"


def render_record_for_llm(record: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if value in (None, "", [], {}):
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
