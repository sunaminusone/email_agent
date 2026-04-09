from __future__ import annotations

import os

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import get_llm
from src.responders.render_helpers import format_product_label, join_sentences
from src.schemas import FinalResponse

from .common import InsufficientContentError, answer


def _product_scope_prefix(scope_block, *, language: str) -> str:
    if not scope_block:
        return ""
    if not scope_block.payload.get("should_acknowledge"):
        return ""

    scope_type = str(scope_block.payload.get("scope_type", "") or "").strip()
    scope_name = str(scope_block.payload.get("scope_name", "") or "").strip()
    scope_source = str(scope_block.payload.get("scope_source", "") or "").strip()
    if scope_type != "product" or not scope_name:
        return ""

    if language == "zh":
        return f"关于{scope_name}产品，"
    if scope_source == "active":
        return f"For the previously discussed product {scope_name}, "
    return f"For the product {scope_name}, "


def _rewrite_product_answer(
    *,
    query: str,
    factual_summary: str,
    fallback_answer: str,
    style: str,
    language: str,
) -> str:
    if language != "en":
        return fallback_answer
    if os.getenv("PYTEST_CURRENT_TEST"):
        return fallback_answer

    tone = "customer support" if style in {"customer_friendly", "sales"} else "helpful customer support"
    system_prompt = (
        "You rewrite grounded product facts into a natural customer-facing reply. "
        "Use only the provided product facts. Do not add facts, specifications, applications, "
        "or claims that are not explicitly present. Keep the answer concise, natural, and direct. "
        "Do not mention retrieval, sources, or that you found a match. Answer in 1-3 sentences."
    )
    human_prompt = (
        f"User question: {query}\n"
        f"Desired tone: {tone}\n"
        f"Grounded product facts: {factual_summary}\n"
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
        return " ".join(text.split())
    except Exception:
        return fallback_answer


def render_product(payload: dict) -> FinalResponse:
    resolution = payload["response_resolution"]
    language = payload["language"]
    style = resolution.reply_style or "concise"
    query = payload["query"]
    content_blocks = payload["content_blocks"]
    blocks = {block.kind: block for block in content_blocks}
    product_blocks = [block for block in content_blocks if block.kind == "product_identity"]
    scope_block = blocks.get("resolved_scope")

    if not product_blocks:
        raise InsufficientContentError("Product renderer requires a product_identity block.")

    parts: list[str] = []
    if len(product_blocks) > 1:
        labels = [
            format_product_label(
                block.payload.get("product_name", "unknown product"),
                block.payload.get("catalog_no", "unknown"),
                language="zh" if language == "zh" else "en",
            )
            for block in product_blocks
        ]
        if language == "zh":
            if style == "sales":
                parts.append(f"我已匹配到多个相关产品：{'；'.join(labels)}。")
            else:
                parts.append(f"当前关联到多个产品：{'；'.join(labels)}。")
        else:
            if style == "sales":
                parts.append(f"I found multiple relevant products for this follow-up: {'; '.join(labels)}.")
            else:
                parts.append(f"This follow-up now points to multiple products: {'; '.join(labels)}.")
    else:
        product_block = product_blocks[0]
        product_name = product_block.payload.get("product_name", "unknown product")
        catalog_no = product_block.payload.get("catalog_no", "unknown")
        business_line = product_block.payload.get("business_line", "unknown")
        general_info_follow_up = bool(product_block.payload.get("general_info_follow_up"))
        scope_intro = _product_scope_prefix(scope_block, language=language)

        if language == "zh":
            if scope_intro:
                parts.append(scope_intro)
            elif general_info_follow_up:
                parts.append(f"这里是 {format_product_label(product_name, catalog_no, language='zh')} 的更多信息。该产品属于 {business_line} 业务线。")
            elif style == "sales":
                parts.append(f"当前最匹配的产品是 {format_product_label(product_name, catalog_no, language='zh')}，属于 {business_line} 业务线。")
            else:
                parts.append(f"有的，当前匹配到的产品是 {format_product_label(product_name, catalog_no, language='zh')}。该产品属于 {business_line} 业务线。")
        else:
            if scope_intro:
                parts.append(scope_intro)
            elif general_info_follow_up:
                parts.append(f"Here is some additional information for {format_product_label(product_name, catalog_no)}. It is listed under {business_line}.")
            elif style == "sales":
                parts.append(f"A strong product match is {format_product_label(product_name, catalog_no)}, listed under {business_line}.")
            else:
                parts.append(f"Yes. The best product match is {format_product_label(product_name, catalog_no)}. It is listed under {business_line}.")

        target_block = blocks.get("target_antigen")
        application_block = blocks.get("application")
        species_block = blocks.get("species_reactivity")
        technical_block = blocks.get("technical_context")
        if language == "zh":
            if target_block and resolution.include_target_antigen:
                parts.append(f"相关靶点是 {target_block.payload.get('target_antigen')}。")
            if application_block and resolution.include_application:
                parts.append(f"适用场景包括 {application_block.payload.get('application_text')}。")
            if species_block and resolution.include_species_reactivity:
                parts.append(f"物种反应性信息为 {species_block.payload.get('species_reactivity_text')}。")
            if technical_block and resolution.include_technical_context:
                parts.append(f"补充信息：{technical_block.payload.get('content_preview', '')[:180]}")
        else:
            if target_block and resolution.include_target_antigen:
                parts.append(f"The target antigen is {target_block.payload.get('target_antigen')}.")
            if application_block and resolution.include_application:
                parts.append(f"Relevant applications include {application_block.payload.get('application_text')}.")
            if species_block and resolution.include_species_reactivity:
                parts.append(f"Species reactivity: {species_block.payload.get('species_reactivity_text')}.")
            if technical_block and resolution.include_technical_context:
                parts.append(f"Additional context: {technical_block.payload.get('content_preview', '')[:220]}")

        factual_parts = [
            f"Product: {product_name} (ID: {catalog_no})",
            f"Business line: {business_line}",
        ]
        if target_block and resolution.include_target_antigen:
            factual_parts.append(f"Target antigen: {target_block.payload.get('target_antigen')}")
        if application_block and resolution.include_application:
            factual_parts.append(f"Applications: {application_block.payload.get('application_text')}")
        if species_block and resolution.include_species_reactivity:
            factual_parts.append(f"Species reactivity: {species_block.payload.get('species_reactivity_text')}")
        if technical_block and resolution.include_technical_context:
            factual_parts.append(f"Technical context: {technical_block.payload.get('content_preview', '')[:220]}")

        deterministic_message = join_sentences(parts)
        message = _rewrite_product_answer(
            query=query,
            factual_summary=" | ".join(part for part in factual_parts if part),
            fallback_answer=deterministic_message,
            style=style,
            language=language,
        )
        if not message:
            raise InsufficientContentError("Product renderer did not produce a message.")
        return answer(message, [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])

    message = join_sentences(parts)
    if not message:
        raise InsufficientContentError("Product renderer did not produce message parts.")
    return answer(message, [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])
