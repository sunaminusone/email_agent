from __future__ import annotations

from typing import Any

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


def format_operational_section(records: list[dict[str, Any]]) -> str:
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
