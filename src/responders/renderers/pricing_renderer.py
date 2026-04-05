from __future__ import annotations

from src.responders.render_helpers import format_currency, format_product_label, humanize_lead_time, join_sentences
from src.schemas import FinalResponse

from .common import InsufficientContentError, answer


def render_pricing(payload: dict) -> FinalResponse:
    resolution = payload["response_resolution"]
    language = payload["language"]
    style = resolution.reply_style or "concise"
    blocks = {block.kind: block for block in payload["content_blocks"]}

    price_block = blocks.get("price")
    lead_time_block = blocks.get("lead_time")
    product_block = blocks.get("product_identity")

    if not price_block and not lead_time_block:
        raise InsufficientContentError("Pricing renderer requires a price or lead-time block.")

    parts: list[str] = []

    if language == "zh":
        if lead_time_block and (resolution.include_lead_time or resolution.answer_focus == "lead_time"):
            lead_time_value = lead_time_block.payload.get("lead_time")
            if lead_time_value:
                parts.append(humanize_lead_time(lead_time_value, language="zh", style=style) + "。")
            else:
                product_name = lead_time_block.payload.get("product_name", "该产品")
                if style == "sales":
                    parts.append(f"我已经匹配到 {product_name}，但当前目录结果里还没有返回明确交期；如果你愿意，我可以继续帮你确认最新交付周期。")
                else:
                    parts.append(f"目前暂未返回 {product_name} 的明确交期信息；如有需要，我可以继续帮你确认。")
        if price_block and (resolution.include_price or resolution.answer_focus == "pricing"):
            price_value = price_block.payload.get("amount")
            if price_value:
                price_text = format_currency(price_value, price_block.payload.get("currency"))
                if style == "sales":
                    parts.append(f"这款产品当前价格为 {price_text}。")
                else:
                    parts.append(f"当前价格为 {price_text}。")
            else:
                product_name = price_block.payload.get("product_name", "该产品")
                if style == "sales":
                    parts.append(f"我已经匹配到 {product_name}，但当前目录结果里还没有返回价格；如果你愿意，我可以继续帮你确认最新报价。")
                else:
                    parts.append(f"目前暂未返回 {product_name} 的价格信息；如有需要，我可以继续帮你确认。")
        if product_block and resolution.include_product_identity:
            parts.append(f"对应产品是 {format_product_label(product_block.payload.get('product_name', 'unknown'), product_block.payload.get('catalog_no', 'unknown'), language='zh')}。")
    else:
        if lead_time_block and (resolution.include_lead_time or resolution.answer_focus == "lead_time"):
            lead_time_value = lead_time_block.payload.get("lead_time")
            product_name = lead_time_block.payload.get("product_name", "this product")
            if lead_time_value:
                lead_time_sentence = humanize_lead_time(lead_time_value, language="en", style=style)
                if style == "sales":
                    parts.append(f"The current expected lead time for {product_name} is {lead_time_value}.")
                elif style == "customer_friendly":
                    parts.append(lead_time_sentence + ".")
                else:
                    parts.append(lead_time_sentence + ".")
            else:
                if style == "sales":
                    parts.append(
                        f"I matched your request to {product_name}, but the current catalog snapshot does not include a confirmed lead time. "
                        "If helpful, I can help you follow up for the latest delivery window."
                    )
                elif style == "customer_friendly":
                    parts.append(
                        f"I found the product match for {product_name}, but I do not have a confirmed lead time in the current catalog snapshot yet."
                    )
                else:
                    parts.append(
                        f"I found the product match for {product_name}, but the current lead time is not available in the catalog snapshot."
                    )
        if price_block and (resolution.include_price or resolution.answer_focus == "pricing"):
            product_name = price_block.payload.get("product_name", "unknown product")
            catalog_no = price_block.payload.get("catalog_no", "unknown")
            price_value = price_block.payload.get("amount")
            if price_value:
                price_text = format_currency(price_value, price_block.payload.get("currency"))
                if style == "sales":
                    parts.append(f"The current commercial price for {product_name} ({catalog_no}) is {price_text}.")
                elif style == "customer_friendly":
                    parts.append(f"The current price for {product_name} ({catalog_no}) is {price_text}.")
                else:
                    parts.append(f"The price for {catalog_no}, {product_name}, is {price_text}.")
            else:
                if style == "sales":
                    parts.append(
                        f"I matched your request to {product_name} ({catalog_no}), but the current catalog snapshot does not include pricing. "
                        "If helpful, I can help you check the latest commercial quote."
                    )
                elif style == "customer_friendly":
                    parts.append(
                        f"I found the product match for {product_name} ({catalog_no}), but I do not have current pricing in the catalog snapshot yet."
                    )
                else:
                    parts.append(
                        f"I found the product match for {product_name} ({catalog_no}), but pricing is not available in the catalog snapshot."
                    )
        if product_block and resolution.include_product_identity:
            parts.append(f"The matched product is {format_product_label(product_block.payload.get('product_name', 'unknown product'), product_block.payload.get('catalog_no', 'unknown'))}.")

    message = join_sentences(parts)
    if not message:
        raise InsufficientContentError("Pricing renderer did not produce message parts.")
    return answer(message, [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])
