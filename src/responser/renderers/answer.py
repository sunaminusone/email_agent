from __future__ import annotations

from src.common.messages import get_message
from src.responser.models import ComposedResponse, ContentBlock, ResponseInput, ResponsePlan


def render_answer_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    blocks = [
        *response_plan.primary_content_blocks,
        *response_plan.supporting_content_blocks,
    ]
    message = _compose_grounded_answer(
        query=response_input.query,
        blocks=blocks,
        should_acknowledge_object=response_plan.should_acknowledge_object,
        locale=response_input.locale,
    )

    response_type = "answer"
    if response_plan.response_mode == "hybrid_answer":
        response_type = "hybrid_answer"

    return ComposedResponse(
        message=message,
        response_type=response_type,
        content_blocks=blocks,
        debug_info={
            "response_mode": response_plan.response_mode,
            "reason": response_plan.reason,
            "should_acknowledge_object": response_plan.should_acknowledge_object,
        },
    )


def _compose_grounded_answer(
    *,
    query: str,
    blocks: list[ContentBlock],
    should_acknowledge_object: bool,
    locale: str = "zh",
) -> str:
    if not blocks:
        return get_message("response_answer_no_result", locale, query=query)

    message_parts: list[str] = []
    object_summary = next((block for block in blocks if block.block_type == "object_summary"), None)
    informational_blocks = [block for block in blocks if block.block_type != "object_summary"]

    if should_acknowledge_object and object_summary is not None and object_summary.body:
        message_parts.append(get_message("response_answer_grounded", locale, object_body=object_summary.body))
    elif informational_blocks:
        message_parts.append(get_message("response_answer_lookup_done", locale, query=query))

    for block in informational_blocks[:3]:
        line = _render_block_line(block, locale)
        if line:
            message_parts.append(line)

    if not informational_blocks and object_summary is not None:
        message_parts.append(get_message("response_answer_resolved_object", locale, object_body=object_summary.body))

    return " ".join(part.strip() for part in message_parts if part.strip()).strip()


def _render_block_line(block: ContentBlock, locale: str = "zh") -> str:
    if block.block_type == "structured_facts":
        if block.body:
            return block.body
        matches = block.data.get("matches", [])
        if matches:
            labels = ", ".join(_safe_label(match) for match in matches[:3] if _safe_label(match))
            return get_message("response_answer_top_matches", locale, labels=labels)
        return ""

    if block.block_type == "technical_snippets":
        return _render_technical_snippets(block)

    if block.block_type == "document_artifacts":
        return get_message("response_answer_matched_docs", locale, body=block.body) if block.body else ""

    if block.block_type == "supporting_records":
        return get_message("response_answer_related_records", locale, body=block.body) if block.body else ""

    return block.body


def _render_technical_snippets(block: ContentBlock) -> str:
    """Render RAG technical snippets into a structured summary.

    Extracts the most relevant content from snippet data, strips metadata
    prefixes (company/tags lines), and composes a concise answer body.
    """
    snippets = block.data.get("snippets", [])
    if not snippets:
        return block.body

    parts: list[str] = []
    for snippet in snippets[:3]:
        content = str(snippet.get("content") or snippet.get("content_preview") or "").strip()
        if not content:
            continue
        cleaned = _clean_snippet_content(content)
        if cleaned:
            parts.append(cleaned)

    return " ".join(parts) if parts else block.body


def _clean_snippet_content(content: str) -> str:
    """Remove metadata prefix lines (company, tags, title) from RAG chunk content."""
    lines = content.split("\n")
    body_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip metadata prefix lines from RAG chunks
        lower = stripped.lower()
        if lower.startswith(("company:", "tags:", "title:")):
            continue
        # Extract body content from "body: ..." prefix
        if lower.startswith("body:"):
            body_lines.append(stripped[5:].strip())
        else:
            body_lines.append(stripped)

    text = " ".join(body_lines).strip()
    # Truncate long snippets to keep response concise
    if len(text) > 500:
        text = text[:497] + "..."
    return text


def _safe_label(record: dict[str, object]) -> str:
    for key in ("display_name", "name", "catalog_no", "order_no", "invoice_no", "file_name"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""
