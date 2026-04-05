from src.responders.common import BaseResponder, ResponseContext, format_address_text


class OperationalResponder(BaseResponder):
    action_type = "draft_reply"

    def render(self, ctx: ResponseContext):
        if ctx.route.route_name != "operational_agent":
            return None

        language = ctx.language
        customer_action = next((a for a in ctx.execution_run.executed_actions if a.action_type == "lookup_customer"), None)
        invoice_action = next((a for a in ctx.execution_run.executed_actions if a.action_type == "lookup_invoice"), None)
        order_action = next((a for a in ctx.execution_run.executed_actions if a.action_type == "lookup_order"), None)
        shipping_action = next((a for a in ctx.execution_run.executed_actions if a.action_type == "lookup_shipping"), None)

        active_actions = [
            action
            for action in [customer_action, invoice_action, order_action, shipping_action]
            if action and action.status in {"completed", "not_found", "blocked"}
        ]
        if len(active_actions) <= 1:
            return None

        sections = []

        if customer_action and customer_action.output.get("matches"):
            top_match = customer_action.output["matches"][0]
            name = top_match.get("display_name") or top_match.get("company_name") or "unknown customer"
            phone = top_match.get("primary_phone") or top_match.get("mobile_phone")
            email = top_match.get("primary_email")
            if language == "zh":
                section = f"客户：{name}"
                if phone:
                    section += f"，电话：{phone}"
                if email:
                    section += f"，邮箱：{email}"
            else:
                section = f"customer: {name}"
                if phone:
                    section += f", phone: {phone}"
                if email:
                    section += f", email: {email}"
            sections.append(section)

        if invoice_action and invoice_action.output.get("matches"):
            top_match = invoice_action.output["matches"][0]
            number = top_match.get("doc_number", "unknown")
            due_date = top_match.get("due_date")
            balance = top_match.get("balance")
            if language == "zh":
                section = f"发票：{number}"
                if due_date:
                    section += f"，到期日：{due_date}"
                if balance is not None:
                    section += f"，余额：{balance}"
            else:
                section = f"invoice: {number}"
                if due_date:
                    section += f", due date: {due_date}"
                if balance is not None:
                    section += f", balance: {balance}"
            sections.append(section)

        if order_action and order_action.output.get("matches"):
            top_match = order_action.output["matches"][0]
            number = top_match.get("doc_number", "unknown")
            ship_date = top_match.get("ship_date")
            if language == "zh":
                section = f"订单：{number}"
                if ship_date:
                    section += f"，发货日期：{ship_date}"
            else:
                section = f"order: {number}"
                if ship_date:
                    section += f", ship date: {ship_date}"
            sections.append(section)

        if shipping_action and shipping_action.output.get("matches"):
            top_match = shipping_action.output["matches"][0]
            number = top_match.get("doc_number", "unknown")
            destination = " ".join(part for part in [top_match.get("ship_city"), top_match.get("ship_country")] if part)
            raw = top_match.get("raw") or {}
            ship_addr = format_address_text(raw.get("ShipAddr", {}) or {})
            if language == "zh":
                section = f"物流：{number}"
                if destination:
                    section += f"，目的地：{destination}"
                elif ship_addr:
                    section += f"，地址：{ship_addr}"
            else:
                section = f"shipping: {number}"
                if destination:
                    section += f", destination: {destination}"
                elif ship_addr:
                    section += f", address: {ship_addr}"
            sections.append(section)

        if not sections:
            return None

        if language == "zh":
            return self.answer(f"我已经完成 Operational Agent 的查询汇总。当前结果：{'；'.join(sections)}。")
        return self.answer(f"I completed the Operational Agent lookup. Current results: {'; '.join(sections)}.")
