from __future__ import annotations

import os
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import get_llm
from src.responders.render_helpers import join_sentences
from src.schemas import FinalResponse

from .common import InsufficientContentError, answer


def _scope_prefix(scope_block, *, language: str) -> str:
    if not scope_block:
        return ""
    if not scope_block.payload.get("should_acknowledge"):
        return ""

    scope_type = str(scope_block.payload.get("scope_type", "") or "").strip()
    scope_name = str(scope_block.payload.get("scope_name", "") or "").strip()
    scope_source = str(scope_block.payload.get("scope_source", "") or "").strip()
    if not scope_type or not scope_name:
        return ""

    if language == "zh":
        if scope_type == "service":
            return f"关于{scope_name}服务，"
        if scope_type == "product":
            return f"关于{scope_name}产品，"
        return ""

    if scope_type == "service":
        if scope_source == "active":
            return f"For the previously discussed {scope_name} service, "
        return f"For the {scope_name} service, "
    if scope_type == "product":
        if scope_source == "active":
            return f"For the previously discussed product {scope_name}, "
        return f"For the product {scope_name}, "
    return ""


def _normalize_preview(preview: str) -> str:
    text = " ".join(str(preview or "").split())
    text = re.sub(r"^ProMab\s+(presents|describes|states that)\s+", "", text, flags=re.I)
    text = re.sub(r"^This section\s+", "", text, flags=re.I)
    text = text.strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _render_direct_answer(
    *,
    language: str,
    style: str,
    query: str,
    preview: str,
    scope_prefix: str,
) -> str:
    normalized_preview = _normalize_preview(preview)
    if language == "zh":
        if style == "concise":
            return f"{scope_prefix}{normalized_preview[:180]}"
        return f"{scope_prefix}{normalized_preview[:220]}"

    if style == "concise":
        body = normalized_preview[:180]
    elif style == "customer_friendly":
        body = normalized_preview[:260]
    else:
        body = normalized_preview[:240]

    if body and scope_prefix and re.match(r"^(a|an|the)\b", body, re.I):
        body = f"the relevant detail is that {body[:1].lower() + body[1:]}"

    if scope_prefix:
        return f"{scope_prefix}{body[:1].lower() + body[1:] if body[:1].isupper() else body}"
    return body


def _rewrite_with_llm(
    *,
    query: str,
    scope_block,
    preview: str,
    fallback_answer: str,
    style: str,
    language: str,
) -> str:
    if language != "en":
        return fallback_answer
    if os.getenv("PYTEST_CURRENT_TEST"):
        return fallback_answer

    scope_type = ""
    scope_name = ""
    if scope_block:
        scope_type = str(scope_block.payload.get("scope_type", "") or "").strip()
        scope_name = str(scope_block.payload.get("scope_name", "") or "").strip()

    scope_line = f"{scope_type}: {scope_name}" if scope_type and scope_name else "none"
    tone = "customer support" if style == "customer_friendly" else "technical customer support"
    system_prompt = (
        "You rewrite grounded technical evidence into a natural customer-facing reply. "
        "Use only the provided technical content. Do not add facts, numbers, timelines, models, "
        "or claims that are not present in the evidence. Keep the answer concise, natural, and direct. "
        "Do not mention documents, matches, retrieval, sources, or that you found material. "
        "Answer in 1-3 sentences."
    )
    human_prompt = (
        f"User question: {query}\n"
        f"Resolved scope: {scope_line}\n"
        f"Desired tone: {tone}\n"
        f"Grounded technical content: {preview}\n"
        f"Fallback draft: {fallback_answer}\n\n"
        "Write the final reply now."
    )

    try:
        llm = get_llm()
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ]
        )
        text = str(getattr(response, "content", "") or "").strip()
        if not text:
            return fallback_answer
        text = " ".join(text.split())
        return text
    except Exception:
        return fallback_answer


def render_technical(payload: dict) -> FinalResponse:
    resolution = payload["response_resolution"]
    language = payload["language"]
    style = resolution.reply_style or "technical"
    query = payload["query"]
    blocks = {block.kind: block for block in payload["content_blocks"]}

    technical_block = blocks.get("technical_context")
    if not technical_block:
        raise InsufficientContentError("Technical renderer requires a technical_context block.")
    scope_block = blocks.get("resolved_scope")

    preview = (technical_block.payload.get("content_preview") or "").strip()
    if not preview:
        raise InsufficientContentError("Technical renderer requires a non-empty technical preview.")

    scope_prefix = _scope_prefix(scope_block, language=language)
    deterministic_message = _render_direct_answer(
        language=language,
        style=style,
        query=query,
        preview=preview,
        scope_prefix=scope_prefix,
    )
    message = _rewrite_with_llm(
        query=query,
        scope_block=scope_block,
        preview=preview,
        fallback_answer=deterministic_message,
        style=style,
        language=language,
    )
    message = join_sentences([message])
    return answer(message, [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])
