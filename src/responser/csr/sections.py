from __future__ import annotations

from typing import Any

_STRUCTURED_FIELD_ORDER: tuple[tuple[str, str], ...] = (
    ("catalog_no", "catalog #"),
    ("price", "price"),
    ("price_min", "price (min)"),
    ("price_max", "price (max)"),
    ("currency", "currency"),
    ("pricing_tier", "pricing tier"),
    ("unit_price", "unit price"),
    ("setup_fee", "setup fee"),
    ("unit", "unit"),
    ("price_note", "price note"),
    ("lead_time_text", "lead time"),
    ("business_line", "business line"),
    ("record_type", "record type"),
    ("product_type", "product type"),
    ("target_antigen", "target antigen"),
    ("application_text", "applications"),
    ("species_reactivity_text", "species reactivity"),
    ("construct", "construct"),
    ("format", "format"),
    ("also_known_as", "also known as"),
    ("source_section", "source section"),
    ("source_excerpt", "source excerpt"),
)

# `name` / `display_name` already in the header line; `price_text` is the
# string form of `price` and would just duplicate; `id` and the matcher
# debug fields (score / match_rank / matched_field / matched_value) are
# implementation noise CSR doesn't need.
_STRUCTURED_HIDDEN_KEYS = frozenset({
    "name", "display_name", "service_name", "price_text", "id", "raw",
    "score", "match_rank", "matched_field", "matched_value",
})

_STRUCTURED_GROUP_LABEL: dict[str, str] = {
    "pricing_lookup_tool": "Pricing lookup matches",
    "catalog_lookup_tool": "Catalog lookup matches",
}


def format_draft_section(draft: str) -> str:
    if not draft:
        return "*📝 Draft reply*\n_(no draft generated — see references below)_"
    return f"*📝 Draft reply* _(CSR: please review & edit before sending)_\n\n{draft}"


def format_trust_section(trust_signal: dict[str, Any]) -> str:
    lines = ["*🧭 Grounding signal*"]
    lines.append(f"   • status: `{trust_signal.get('grounding_status', 'unknown')}`")
    lines.append(f"   • retrieval quality: `{trust_signal.get('retrieval_quality_tier', 'unknown')}`")
    lines.append(f"   • {trust_signal.get('summary', '')}")
    return "\n".join(lines)


def format_threads_section(threads: list[dict[str, Any]], *, trust_signal: dict[str, Any]) -> str:
    lines = ["*📚 Similar past inquiries*"]
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
                lines.append(format_attachments_line(attachments))
    return "\n".join(lines)


def format_attachments_line(attachments: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for att in attachments:
        name = att.get("name") or att.get("id") or "file"
        ext = att.get("extension") or ""
        url = att.get("url") or ""
        label = f"{name}.{ext}" if ext and not str(name).lower().endswith(f".{ext.lower()}") else name
        parts.append(f"<{url}|{label}>" if url else label)
    return "   📎 " + " · ".join(parts)


def format_documents_section(matches: list[dict[str, Any]], *, trust_signal: dict[str, Any]) -> str:
    lines = ["*📄 Relevant documents*"]
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


def format_routing_section(notes: list[str]) -> str:
    lines = ["*⚠️ AI routing notes* _(the agent flagged these — judgment call for the CSR)_"]
    for note in notes:
        lines.append(f"   • {note}")
    return "\n".join(lines)


def format_structured_section(records: list[dict[str, Any]]) -> str:
    lines = ["*💰 Live catalog / pricing facts* _(from postgres — authoritative)_"]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        source = str(record.get("_source_tool") or "unknown_tool")
        by_source.setdefault(source, []).append(record)

    curated = {key for key, _ in _STRUCTURED_FIELD_ORDER}

    for source, group in by_source.items():
        group_label = _STRUCTURED_GROUP_LABEL.get(source, source)
        lines.append(f"\n   _{group_label}:_")
        for i, record in enumerate(group, 1):
            label = (
                record.get("display_name")
                or record.get("name")
                or record.get("service_name")
                or record.get("catalog_no")
                or f"record {i}"
            )
            lines.append(f"\n   *[{i}]* {label}")

            for key, label_text in _STRUCTURED_FIELD_ORDER:
                value = record.get(key)
                if value in (None, "", []):
                    continue
                lines.append(f"      • {label_text}: `{value}`")

            # Surface unexpected fields (so new serializer keys aren't silently
            # dropped), but skip hidden internal keys and anything we already
            # rendered above. Mirrors the operational-records pattern.
            for key, value in record.items():
                if key in curated or key in _STRUCTURED_HIDDEN_KEYS or key.startswith("_"):
                    continue
                if value in (None, "", [], {}):
                    continue
                lines.append(f"      • {key}: `{value}`")
    return "\n".join(lines)


def format_document_files_section(files: list[dict[str, Any]]) -> str:
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


def format_service_document_section(document: dict[str, Any]) -> str:
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


_OPERATIONAL_FIELD_ORDER: tuple[tuple[str, str], ...] = (
    ("payment_status", "status"),
    ("balance", "balance due"),
    ("total_amt", "total"),
    ("txn_date", "date"),
    ("due_date", "due"),
    ("ship_date", "shipped"),
    ("billing_email", "billing email"),
    ("ship_city", "ship to"),
    ("ship_country", "country"),
    ("email_status", "email status"),
    ("print_status", "print status"),
    ("last_updated_at", "last updated"),
)

# Internal IDs, the raw QuickBooks payload, and fields already in the header.
# `days_past_due` is the numeric companion to `payment_status` — already in the header line.
_OPERATIONAL_HIDDEN_KEYS = frozenset({
    "raw", "id", "customer_id", "entity", "doc_number", "customer_name", "days_past_due",
})

_CURRENCY_FIELDS = frozenset({"balance", "total_amt"})
_DATE_FIELDS = frozenset({"txn_date", "due_date", "ship_date", "last_updated_at"})


def _format_currency(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_operational_value(field: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if field in _CURRENCY_FIELDS:
        return _format_currency(value)
    if field in _DATE_FIELDS:
        s = str(value)
        return s[:10] if len(s) >= 10 else s
    return str(value)


def _format_invoice_line_items(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return []
    out: list[str] = []
    for line in raw.get("Line") or []:
        if not isinstance(line, dict):
            continue
        detail_type = line.get("DetailType")
        amount = line.get("Amount")
        if detail_type == "SalesItemLineDetail":
            detail = line.get("SalesItemLineDetail") or {}
            qty = detail.get("Qty")
            unit_price = detail.get("UnitPrice")
            description = line.get("Description") or (detail.get("ItemRef") or {}).get("name") or "item"
            parts: list[str] = []
            if qty is not None:
                parts.append(f"{qty}×")
            parts.append(str(description))
            if unit_price is not None:
                parts.append(f"@ {_format_currency(unit_price)}")
            if amount is not None:
                parts.append(f"= {_format_currency(amount)}")
            out.append("      • " + " ".join(parts))
        elif detail_type == "DiscountLineDetail":
            detail = line.get("DiscountLineDetail") or {}
            pct = detail.get("DiscountPercent")
            if pct is not None and amount is not None:
                out.append(f"      • discount: −{pct}% ({_format_currency(amount)})")
            elif amount is not None:
                out.append(f"      • discount: −{_format_currency(amount)}")
        elif detail_type == "SubTotalLineDetail" and amount is not None:
            out.append(f"      • subtotal: {_format_currency(amount)}")
    return out


_ENTITY_GROUP_LABEL: dict[str, str] = {
    "Invoice": "Invoices",
    "SalesReceipt": "Sales receipts",
    "Customer": "Customer records",
}


def format_operational_section(records: list[dict[str, Any]]) -> str:
    lines = ["*📋 Operational records (QuickBooks)* _(authoritative — order / invoice / shipping)_"]
    # Group by QuickBooks entity (Invoice / SalesReceipt / Customer) rather
    # than by source tool: order_lookup_tool / invoice_lookup_tool /
    # shipping_lookup_tool all hit the same QB SearchTransactions endpoint,
    # so the same Invoice row can surface from any of them — labelling the
    # group by tool name is implementation noise. CSR cares which kind of
    # record it is.
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        entity = str(record.get("entity") or "").strip() or "Other"
        by_entity.setdefault(entity, []).append(record)

    curated = {key for key, _ in _OPERATIONAL_FIELD_ORDER}

    for entity, group in by_entity.items():
        group_label = _ENTITY_GROUP_LABEL.get(entity, entity)
        lines.append(f"\n   _{group_label}:_")
        for i, record in enumerate(group, 1):
            entity = str(record.get("entity") or "").strip() or "record"
            doc_number = record.get("doc_number") or record.get("id") or ""
            customer = record.get("customer_name") or ""
            header_parts = [f"*[{i}]* {entity}"]
            if doc_number:
                header_parts.append(f"#{doc_number}")
            if customer:
                header_parts.append(f"— {customer}")
            lines.append(f"\n   {' '.join(header_parts)}")

            for key, label in _OPERATIONAL_FIELD_ORDER:
                formatted = _format_operational_value(key, record.get(key))
                if formatted:
                    lines.append(f"      • {label}: `{formatted}`")

            # Surface unexpected fields (so new serializer keys aren't silently dropped),
            # but skip hidden internal keys and anything we already rendered above.
            for key, value in record.items():
                if key in curated or key in _OPERATIONAL_HIDDEN_KEYS or key.startswith("_"):
                    continue
                if value in (None, "", [], {}):
                    continue
                lines.append(f"      • {key}: `{value}`")

            if entity in {"Invoice", "SalesReceipt"}:
                item_lines = _format_invoice_line_items(record.get("raw"))
                if item_lines:
                    lines.append("      _line items:_")
                    lines.extend(item_lines)
    return "\n".join(lines)
