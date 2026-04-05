from __future__ import annotations

from src.responders.render_helpers import format_document_scope, join_sentences
from src.schemas import FinalResponse

from .common import InsufficientContentError, answer


def render_document(payload: dict) -> FinalResponse:
    resolution = payload["response_resolution"]
    language = payload["language"]
    style = resolution.reply_style or "concise"
    blocks = {block.kind: block for block in payload["content_blocks"]}
    document_block = blocks.get("documents")

    if not document_block:
        raise InsufficientContentError("Document renderer requires a documents block.")

    file_name = document_block.payload.get("file_name", "unknown document")
    scope = format_document_scope(document_block.payload.get("product_scope", ""), language=language)
    found = bool(document_block.payload.get("found"))
    requested_types = document_block.payload.get("requested_document_types", []) or []
    requested_label = requested_types[0] if requested_types else "document"
    product_block = blocks.get("product_identity")

    parts: list[str] = []
    if language == "zh":
        if found:
            if style == "sales":
                parts.append(f"我为你找到了最适合分享的资料：《{file_name}》。你可以直接打开结果中的文档链接查看。")
            elif style == "customer_friendly":
                parts.append(f"我找到了可以直接分享的资料：《{file_name}》。你可以直接打开结果中的文档链接查看。")
            else:
                parts.append(f"当前最匹配的是《{file_name}》。你可以直接打开结果中的文档链接查看。")
        elif product_block:
            parts.append(f"当前文档目录里没有找到与 {product_block.payload.get('catalog_no', product_block.payload.get('product_name', '该产品'))} 直接对应的{requested_label}。")
        else:
            parts.append(f"当前文档目录里没有找到直接匹配的{requested_label}。")
        if found and product_block and resolution.include_product_identity:
            parts.append(f"这些资料与 {product_block.payload.get('catalog_no', product_block.payload.get('product_name', '该产品'))} 相关。")
    else:
        if found:
            if style == "sales":
                parts.append(f"I found a strong document match you can share: {file_name} ({scope}). You can open it from the document results below.")
            elif style == "customer_friendly":
                parts.append(f"I found a document you can share directly: {file_name} ({scope}). You can open it from the document results below.")
            elif style == "technical":
                parts.append(f"The most relevant document is {file_name} ({scope}). You can open it from the document results below.")
            else:
                parts.append(f"The best current match is {file_name} ({scope}), and you can open it from the document results below.")
        elif product_block:
            product_label = product_block.payload.get("catalog_no") or product_block.payload.get("product_name", "this item")
            if style == "sales":
                parts.append(
                    f"I couldn't find a {requested_label} specifically for {product_label} in the current document catalog. "
                    "If helpful, I can help you share the closest product-line material instead."
                )
            elif style == "customer_friendly":
                parts.append(
                    f"I couldn't find a {requested_label} specifically for {product_label} in the current document catalog yet."
                )
            else:
                parts.append(f"I couldn't find a {requested_label} specifically for {product_label} in the current document catalog.")
        else:
            parts.append(f"I couldn't find a matching {requested_label} in the current document catalog.")
        if found and product_block and resolution.include_product_identity:
            parts.append(f"This documentation is related to {product_block.payload.get('catalog_no', product_block.payload.get('product_name', 'this item'))}.")

    message = join_sentences(parts)
    if not message:
        raise InsufficientContentError("Document renderer did not produce message parts.")
    return answer(message, [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])
