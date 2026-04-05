from __future__ import annotations

from src.responders.render_helpers import join_sentences
from src.schemas import FinalResponse

from .common import InsufficientContentError, answer


def render_technical(payload: dict) -> FinalResponse:
    resolution = payload["response_resolution"]
    language = payload["language"]
    style = resolution.reply_style or "technical"
    query = payload["query"]
    blocks = {block.kind: block for block in payload["content_blocks"]}

    technical_block = blocks.get("technical_context")
    if not technical_block:
        raise InsufficientContentError("Technical renderer requires a technical_context block.")

    preview = (technical_block.payload.get("content_preview") or "").strip()
    file_name = technical_block.payload.get("file_name") or "the knowledge base"
    if not preview:
        raise InsufficientContentError("Technical renderer requires a non-empty technical preview.")

    if language == "zh":
        if style == "customer_friendly":
            message = f"我找到了可以直接解释给客户的技术资料。当前最相关的内容来自 {file_name}：{preview[:220]}"
        else:
            message = f"我找到了相关技术资料。当前最相关的内容来自 {file_name}，可作为回答“{query}”的依据：{preview[:220]}"
    else:
        if style == "concise":
            message = f"Relevant technical material: {file_name} - {preview[:180]}"
        elif style == "customer_friendly":
            message = f"I found technical material that can be explained clearly to a customer. The strongest current source is {file_name}: {preview[:220]}"
        else:
            message = f'I found relevant technical material for "{query}". The strongest current match is from {file_name}: {preview[:220]}'

    message = join_sentences([message])
    return answer(message, [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])
