from src.responders.common import BaseResponder, ResponseContext


def _format_price_value(match):
    price_value = match.get("price_text") or match.get("price")
    if price_value is None:
        return None
    return f"{price_value} {match.get('currency') or 'USD'}"


def _should_defer_to_specific_responder(ctx: ResponseContext) -> bool:
    query = (ctx.query or "").lower()
    flags = ctx.agent_input.request_flags
    if flags.needs_price or flags.needs_quote or flags.needs_timeline:
        return True
    if flags.needs_documentation:
        return True
    if any(term in query for term in ["price", "pricing", "quote", "cost", "lead time", "brochure", "datasheet", "flyer", "document"]):
        return True
    return False


class CommercialResponder(BaseResponder):
    action_type = "draft_reply"

    def render(self, ctx: ResponseContext):
        if ctx.route.route_name != "commercial_agent":
            return None
        if ctx.response_resolution.should_suppress_generic_summary:
            return None
        if _should_defer_to_specific_responder(ctx):
            return None

        language = ctx.language
        product_action = next((a for a in ctx.execution_run.executed_actions if a.action_type == "lookup_catalog_product"), None)
        price_action = next((a for a in ctx.execution_run.executed_actions if a.action_type == "lookup_price"), None)
        document_action = next((a for a in ctx.execution_run.executed_actions if a.action_type == "lookup_document"), None)
        technical_action = next((a for a in ctx.execution_run.executed_actions if a.action_type == "retrieve_technical_knowledge"), None)

        active_actions = [
            action
            for action in [product_action, price_action, document_action, technical_action]
            if action and action.status in {"completed", "not_found", "blocked"}
        ]
        if len(active_actions) <= 1:
            return None

        sections = []

        if product_action and product_action.output.get("matches"):
            top_match = product_action.output["matches"][0]
            product_name = top_match.get("name") or top_match.get("display_name") or "unknown"
            product_no = top_match.get("catalog_no") or "unknown"
            if language == "zh":
                sections.append(f"产品：{product_name}（编号：{product_no}）")
            else:
                sections.append(f"product: {product_name} (ID: {product_no})")

        if price_action and price_action.output.get("matches"):
            top_match = price_action.output["matches"][0]
            price_value = _format_price_value(top_match)
            lead_time = top_match.get("lead_time_text")
            if price_value:
                if language == "zh":
                    sections.append(f"价格：{price_value}")
                else:
                    sections.append(f"price: {price_value}")
            if lead_time:
                if language == "zh":
                    sections.append(f"交期：{lead_time}")
                else:
                    sections.append(f"lead time: {lead_time}")

        if document_action:
            matches = document_action.output.get("matches", [])
            if matches:
                file_names = [match.get("file_name") for match in matches[:3] if match.get("file_name")]
                if file_names:
                    if language == "zh":
                        sections.append(f"文档：{'；'.join(file_names)}")
                    else:
                        sections.append(f"documents: {'; '.join(file_names)}")

        if technical_action and technical_action.output.get("matches"):
            top_match = technical_action.output["matches"][0]
            preview = (top_match.get("content_preview") or "").strip()
            if preview:
                if language == "zh":
                    sections.append(f"技术要点：{preview[:160]}")
                else:
                    sections.append(f"technical note: {preview[:160]}")

        if not sections:
            return None

        if language == "zh":
            return self.answer(f"我已经完成 Commercial Agent 的查询汇总。当前结果：{'；'.join(sections)}。")
        return self.answer(f"I completed the Commercial Agent lookup. Current results: {'; '.join(sections)}.")
