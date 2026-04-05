from __future__ import annotations

from src.responders.render_helpers import format_product_label, join_sentences
from src.schemas import FinalResponse

from .common import InsufficientContentError, answer


def render_product(payload: dict) -> FinalResponse:
    resolution = payload["response_resolution"]
    language = payload["language"]
    style = resolution.reply_style or "concise"
    content_blocks = payload["content_blocks"]
    blocks = {block.kind: block for block in content_blocks}
    product_blocks = [block for block in content_blocks if block.kind == "product_identity"]

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

        if language == "zh":
            if general_info_follow_up:
                parts.append(f"这里是 {format_product_label(product_name, catalog_no, language='zh')} 的更多信息。该产品属于 {business_line} 业务线。")
            elif style == "sales":
                parts.append(f"当前最匹配的产品是 {format_product_label(product_name, catalog_no, language='zh')}，属于 {business_line} 业务线。")
            else:
                parts.append(f"有的，当前匹配到的产品是 {format_product_label(product_name, catalog_no, language='zh')}。该产品属于 {business_line} 业务线。")
        else:
            if general_info_follow_up:
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

    message = join_sentences(parts)
    if not message:
        raise InsufficientContentError("Product renderer did not produce message parts.")
    return answer(message, [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])
