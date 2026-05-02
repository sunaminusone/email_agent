from __future__ import annotations

from textwrap import indent
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict

from src.config import get_llm
from src.responser.csr.extractors import PAYMENT_STATUS_VOCABULARY

_DRAFT_SYSTEM_PROMPT = """\
You are drafting a customer-service reply for a customer-service representative
(CSR) at ProMab Biotechnologies. The CSR will review and edit your draft
before sending — your job is to give them a strong starting point.

Inputs you will see:
1. The new customer inquiry.
2. ASKED FOCUS — the specific question(s) the upstream parser identified in
   the inquiry. This is your answer target.
3. STRUCTURED LIVE FACTS — catalog / pricing records from our live database
   (only present when the corresponding tools fired and returned matches).
4. Past similar inquiries with how our sales team replied to them.
5. Relevant documentation chunks from our knowledge base.
6. OPERATIONAL RECORDS — order / invoice / shipping / customer data from
   QuickBooks (only present when those tools fired).

Rules:
- Write a clear, professional draft reply addressed to the new customer.
- ANSWER ONLY THE ASKED FOCUS. If ASKED FOCUS lists one ask, answer that
  one. If it lists several (separated by ";"), answer each. Do NOT
  volunteer adjacent fields the customer did not ask about (e.g. don't
  report payment status when only the send date was asked, don't quote
  price when only the lead time was asked).
- If the requested information is NOT present in the data we retrieved,
  say so EXPLICITLY ("we don't have a record of when the invoice was
  emailed to you" / "I don't see a delivery timestamp on file") instead
  of substituting a related field. Never present a different field as if
  it answered the question.
- STRUCTURED LIVE FACTS are AUTHORITATIVE. When live catalog / pricing
  records are present, cite catalog_no, price, currency, and lead_time
  EXACTLY as given — do NOT round, paraphrase, or pull these numbers from
  past sales emails (which may be outdated). If past sales emails contradict
  the live data, trust the live data and ignore the email's number.
- Service-flyer pricing semantics (records sourced from service flyers):
  * If a record has `plan_total_price` set, that IS the bundled plan
    total — cite it directly when the customer asks about plan cost.
  * Otherwise, a flyer pricing record represents a SINGLE PHASE of a
    multi-phase plan (look for `plan_name` and `phase_name`). Its
    `price` is the phase price, not the plan total.
  * `optional: yes` means that phase is not always included — its
    price only applies if the customer chooses to include it.
  * Do NOT sum phase prices into an implied "plan total" yourself.
    Either cite `plan_total_price` directly, or — if no record has it
    — say plan-level total isn't in the data and list phase prices
    with their plan/phase context (e.g. "Plan A · Phase III: $7,350 —
    vector construction"), noting that the full quote depends on
    selected phases.
- OPERATIONAL RECORDS (orders / invoices / shipping) are also authoritative —
  cite order numbers, statuses, and tracking IDs exactly as given.
- QuickBooks field semantics (don't mistranslate these):
  * `email_status: NotSet` / `print_status: NotSet` mean the document was
    NEVER sent via QuickBooks email / print — not "we have no record".
    `EmailSent` means it was sent but QB does not store the timestamp.
    `NeedToSend` means it's queued / marked to be sent but has not actually
    been emailed yet (this drives the `(not sent)` suffix on payment_status).
    None of these statuses carry a send DATE.
  * `txn_date` is when the document was CREATED in QuickBooks (issue date),
    NOT when it was sent / delivered to the customer.
  * `due_date` is the payment due date, not a send or delivery date.
  * `ship_date` is the goods-shipped date, not the document-sent date.
  * `last_updated_at` is the most recent edit timestamp on the QB record —
    NOT a send / delivery / payment date.
  * `balance` is the still-unpaid amount; `total_amt` is the invoice's full
    value. `balance == 0` confirms full payment.
  * On Customer records, `balance` / `open_balance` are the customer's TOTAL
    outstanding amount across all their invoices, not a per-invoice figure.
  * `payment_status` is derived from balance / due_date / email_status
    (Invoice records only — SalesReceipts skip this). Possible values:
__PAYMENT_STATUS_VOCABULARY__
    Do NOT volunteer payment status unless the customer asked about it.
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
""".replace(
    "__PAYMENT_STATUS_VOCABULARY__",
    indent(PAYMENT_STATUS_VOCABULARY, "    "),
)


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


def _build_draft_prompts(
    *,
    query: str,
    asked_focus: str | None,
    threads: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    structured_records: list[dict[str, Any]],
    operational_records: list[dict[str, Any]],
    trust_signal: dict[str, Any],
    primary_service_document: dict[str, Any] | None,
) -> tuple[str, str]:
    parts: list[str] = []
    parts.append(f"NEW CUSTOMER INQUIRY:\n{query}\n")

    focus_text = (asked_focus or "").strip()
    if focus_text:
        parts.append(
            "\nASKED FOCUS (parser-identified asks — answer ONLY these; if any "
            "asked item is not in the retrieved data, say so explicitly rather "
            "than substituting a related field):\n"
            f"{focus_text}\n"
        )
    else:
        parts.append(
            "\nASKED FOCUS: (no specific ask identified — likely a greeting / "
            "acknowledgement / closing; reply briefly without volunteering data)\n"
        )

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
    system_prompt = _build_system_prompt(
        grounding_status=str(trust_signal.get("grounding_status") or ""),
        primary_service_document=primary_service_document,
    )
    return system_prompt, user_prompt


def generate_draft(
    *,
    query: str,
    asked_focus: str | None,
    threads: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    structured_records: list[dict[str, Any]],
    operational_records: list[dict[str, Any]],
    trust_signal: dict[str, Any],
    primary_service_document: dict[str, Any] | None,
) -> str:
    if not query.strip():
        return ""

    system_prompt, user_prompt = _build_draft_prompts(
        query=query,
        asked_focus=asked_focus,
        threads=threads,
        documents=documents,
        structured_records=structured_records,
        operational_records=operational_records,
        trust_signal=trust_signal,
        primary_service_document=primary_service_document,
    )

    try:
        llm = get_llm().with_structured_output(DraftOutput)
        result = llm.invoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        return str(getattr(result, "draft", "") or "").strip()
    except Exception as exc:
        return f"[Draft generation failed: {exc}. CSR: please draft manually using the references below.]"


def stream_draft(
    *,
    query: str,
    asked_focus: str | None,
    threads: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    structured_records: list[dict[str, Any]],
    operational_records: list[dict[str, Any]],
    trust_signal: dict[str, Any],
    primary_service_document: dict[str, Any] | None,
) -> Iterator[str]:
    """Yield draft text token-by-token. Drops with_structured_output since we
    just want a raw text stream (the structured wrapper would produce partial
    JSON chunks instead of clean tokens)."""
    if not query.strip():
        return

    system_prompt, user_prompt = _build_draft_prompts(
        query=query,
        asked_focus=asked_focus,
        threads=threads,
        documents=documents,
        structured_records=structured_records,
        operational_records=operational_records,
        trust_signal=trust_signal,
        primary_service_document=primary_service_document,
    )

    try:
        llm = get_llm()
        for chunk in llm.stream([
            ("system", system_prompt),
            ("human", user_prompt),
        ]):
            text = getattr(chunk, "content", "") or ""
            if text:
                yield text
    except Exception as exc:
        yield f"[Draft generation failed: {exc}. CSR: please draft manually using the references below.]"


_LLM_RECORD_HIDDEN_KEYS = frozenset({"raw", "id", "customer_id"})


def render_record_for_llm(record: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in record.items():
        if key.startswith("_") or key in _LLM_RECORD_HIDDEN_KEYS:
            continue
        if value in (None, "", [], {}):
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
