from __future__ import annotations

from src.response.models import ComposedResponse, ContentBlock, ResponseInput, ResponsePlan


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
) -> str:
    if not blocks:
        return f"I analyzed the request about '{query}', but there was no grounded result to return."

    message_parts: list[str] = []
    object_summary = next((block for block in blocks if block.block_type == "object_summary"), None)
    informational_blocks = [block for block in blocks if block.block_type != "object_summary"]

    if should_acknowledge_object and object_summary is not None and object_summary.body:
        message_parts.append(f"I found grounded information for {object_summary.body}.")
    elif informational_blocks:
        message_parts.append(f"I completed the requested lookup for '{query}'.")

    for block in informational_blocks[:3]:
        line = _render_block_line(block)
        if line:
            message_parts.append(line)

    if not informational_blocks and object_summary is not None:
        message_parts.append(f"Resolved object: {object_summary.body}.")

    return " ".join(part.strip() for part in message_parts if part.strip()).strip()


def _render_block_line(block: ContentBlock) -> str:
    if block.block_type == "structured_facts":
        if block.body:
            return block.body
        matches = block.data.get("matches", [])
        if matches:
            return f"Top matches: {', '.join(_safe_label(match) for match in matches[:3] if _safe_label(match))}."
        return ""

    if block.block_type == "technical_snippets":
        return block.body

    if block.block_type == "document_artifacts":
        return f"Matched documents: {block.body}." if block.body else ""

    if block.block_type == "supporting_records":
        return f"Related records: {block.body}." if block.body else ""

    return block.body


def _safe_label(record: dict[str, object]) -> str:
    for key in ("display_name", "name", "catalog_no", "order_no", "invoice_no", "file_name"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""
