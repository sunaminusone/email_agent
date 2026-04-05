from __future__ import annotations

from src.responders.common import format_address_text
from src.schemas import FinalResponse

from .common import InsufficientContentError, answer


def _status_update(message: str, action_type: str) -> FinalResponse:
    return FinalResponse(message=message, response_type="status_update", grounded_action_types=[action_type])


def _clarification(message: str, missing: list[str], action_type: str) -> FinalResponse:
    return FinalResponse(
        message=message,
        response_type="clarification",
        missing_information_requested=missing,
        grounded_action_types=[action_type],
    )


def _render_customer(block, language: str) -> FinalResponse:
    status = block.payload.get("status", "")
    match = block.payload.get("match") or {}

    if status == "not_configured":
        message = (
            "客户与线索查询模块已经接到 QuickBooks，但当前还没有完成配置。请先在 .env 中补齐 QB_CLIENT_ID、QB_CLIENT_SECRET 和 QB_REDIRECT_URI。"
            if language == "zh"
            else "The customer and leads lookup flow is wired to QuickBooks, but the integration is not configured yet. Please set QB_CLIENT_ID, QB_CLIENT_SECRET, and QB_REDIRECT_URI in .env first."
        )
        return _status_update(message, "lookup_customer")
    if status == "not_connected":
        message = (
            "QuickBooks 已配置，但还没有完成授权连接。请先打开 /qb/connect 完成 OAuth 授权，再重新查询客户或线索信息。"
            if language == "zh"
            else "QuickBooks is configured but not connected yet. Open /qb/connect to complete OAuth, then retry the customer or lead lookup."
        )
        return _status_update(message, "lookup_customer")
    if status == "needs_input":
        message = (
            "我已经进入客户与线索查询流程，但还缺少可用于 QuickBooks 查询的客户名称或公司名称。"
            if language == "zh"
            else "I reached the customer and leads lookup flow, but I still need a customer or company name."
        )
        missing = ["客户名称或公司名称"] if language == "zh" else ["customer or company name"]
        return _clarification(message, missing, "lookup_customer")
    if not match:
        message = (
            "我已经识别到这是客户与线索查询问题，但当前还没有查到匹配的 QuickBooks Customer 记录。请确认客户名称或公司名称是否准确。"
            if language == "zh"
            else "I identified this as a customer or lead lookup request, but I did not find a matching QuickBooks Customer record yet. Please confirm the customer or company name."
        )
        return _status_update(message, "lookup_customer")

    display_name = match.get("display_name") or match.get("company_name") or "unknown customer"
    company_name = match.get("company_name")
    primary_phone = match.get("primary_phone") or match.get("mobile_phone")
    primary_email = match.get("primary_email")
    open_balance = match.get("open_balance")
    bill_address_text = format_address_text(match.get("bill_addr") or {})
    ship_address_text = format_address_text(match.get("ship_addr") or {})

    if language == "zh":
        details = [f"客户：{display_name}"]
        if company_name and company_name != display_name:
            details.append(f"公司：{company_name}")
        if primary_phone:
            details.append(f"电话：{primary_phone}")
        if primary_email:
            details.append(f"邮箱：{primary_email}")
        if open_balance is not None:
            details.append(f"未结余额：{open_balance}")
        if bill_address_text:
            details.append(f"账单地址：{bill_address_text}")
        if ship_address_text:
            details.append(f"收货地址：{ship_address_text}")
        return answer(f"我已经从 QuickBooks 找到对应的客户/线索资料。当前最匹配结果为：{'；'.join(details)}。", ["lookup_customer"])

    details = [f"customer: {display_name}"]
    if company_name and company_name != display_name:
        details.append(f"company: {company_name}")
    if primary_phone:
        details.append(f"phone: {primary_phone}")
    if primary_email:
        details.append(f"email: {primary_email}")
    if open_balance is not None:
        details.append(f"open balance: {open_balance}")
    if bill_address_text:
        details.append(f"billing address: {bill_address_text}")
    if ship_address_text:
        details.append(f"shipping address: {ship_address_text}")
    return answer(f"I found a matching QuickBooks customer or lead record. Current best match: {'; '.join(details)}.", ["lookup_customer"])


def _render_invoice(block, language: str) -> FinalResponse:
    status = block.payload.get("status", "")
    match = block.payload.get("match") or {}

    if status == "not_configured":
        message = "invoice 查询模块已经接到 QuickBooks，但当前还没有完成配置。请先在 .env 中补齐 QB_CLIENT_ID、QB_CLIENT_SECRET 和 QB_REDIRECT_URI。" if language == "zh" else "The invoice lookup flow is wired to QuickBooks, but the integration is not configured yet. Please set QB_CLIENT_ID, QB_CLIENT_SECRET, and QB_REDIRECT_URI in .env first."
        return _status_update(message, "lookup_invoice")
    if status == "not_connected":
        message = "QuickBooks 已配置，但还没有完成授权连接。请先打开 /qb/connect 完成 OAuth 授权，再重新查询 invoice。" if language == "zh" else "QuickBooks is configured but not connected yet. Open /qb/connect to complete OAuth, then retry the invoice lookup."
        return _status_update(message, "lookup_invoice")
    if status == "needs_input":
        message = "我已经进入 invoice 查询流程，但还缺少可用于 QuickBooks 查询的 invoice number 或客户名称。" if language == "zh" else "I reached the invoice lookup flow, but I still need an invoice number or customer name."
        missing = ["invoice number 或客户名称"] if language == "zh" else ["invoice number or customer name"]
        return _clarification(message, missing, "lookup_invoice")
    if not match:
        message = "我已经识别到这是 invoice 查询问题，但当前还没有查到匹配的 QuickBooks invoice 记录。请确认 invoice number 或客户名称是否准确。" if language == "zh" else "I identified this as an invoice lookup request, but I did not find a matching QuickBooks invoice yet. Please confirm the invoice number or customer name."
        return _status_update(message, "lookup_invoice")

    doc_number = match.get("doc_number", "unknown")
    customer_name = match.get("customer_name") or "unknown customer"
    total_amt = match.get("total_amt")
    balance = match.get("balance")
    txn_date = match.get("txn_date")
    due_date = match.get("due_date")
    raw = match.get("raw") or {}
    bill_address_text = format_address_text(raw.get("BillAddr", {}) or {})
    ship_address_text = format_address_text(raw.get("ShipAddr", {}) or {})

    if language == "zh":
        details = [f"发票号：{doc_number}", f"客户：{customer_name}"]
        if txn_date:
            details.append(f"开票日期：{txn_date}")
        if due_date:
            details.append(f"到期日：{due_date}")
        if total_amt is not None:
            details.append(f"总额：{total_amt}")
        if balance is not None:
            details.append(f"未结余额：{balance}")
        if bill_address_text:
            details.append(f"账单地址：{bill_address_text}")
        if ship_address_text:
            details.append(f"收货地址：{ship_address_text}")
        return answer(f"我已经从 QuickBooks 找到对应的 invoice 记录。当前最匹配结果为：{'；'.join(details)}。", ["lookup_invoice"])

    details = [f"invoice number: {doc_number}", f"customer: {customer_name}"]
    if txn_date:
        details.append(f"invoice date: {txn_date}")
    if due_date:
        details.append(f"due date: {due_date}")
    if total_amt is not None:
        details.append(f"total: {total_amt}")
    if balance is not None:
        details.append(f"balance: {balance}")
    if bill_address_text:
        details.append(f"billing address: {bill_address_text}")
    if ship_address_text:
        details.append(f"shipping address: {ship_address_text}")
    return answer(f"I found a matching QuickBooks invoice record. Current best match: {'; '.join(details)}.", ["lookup_invoice"])


def _render_order(block, language: str) -> FinalResponse:
    status = block.payload.get("status", "")
    match = block.payload.get("match") or {}

    if status == "not_configured":
        message = "订单查询模块已经接到 QuickBooks，但当前还没有完成配置。请先在 .env 中补齐 QB_CLIENT_ID、QB_CLIENT_SECRET 和 QB_REDIRECT_URI。" if language == "zh" else "The order lookup flow is wired to QuickBooks, but the integration is not configured yet. Please set QB_CLIENT_ID, QB_CLIENT_SECRET, and QB_REDIRECT_URI in .env first."
        return _status_update(message, "lookup_order")
    if status == "not_connected":
        message = "QuickBooks 已配置，但还没有完成授权连接。请先打开 /qb/connect 完成 OAuth 授权，再重新查询订单。" if language == "zh" else "QuickBooks is configured but not connected yet. Open /qb/connect to complete the OAuth flow, then retry the order lookup."
        return _status_update(message, "lookup_order")
    if status == "needs_input":
        message = "我已经进入订单查询流程，但还缺少可用于 QuickBooks 查询的关键信息。请提供订单号、invoice number，或客户名称。" if language == "zh" else "I reached the QuickBooks order lookup flow, but I still need a usable identifier. Please share an order number, invoice number, or customer name."
        missing = ["订单号、invoice number，或客户名称"] if language == "zh" else ["order number, invoice number, or customer name"]
        return _clarification(message, missing, "lookup_order")
    if not match:
        message = "我已经识别到这是订单相关问题，但当前还没有查到匹配的 QuickBooks 订单或发票记录。请确认订单号、invoice number，或提供更准确的客户名称。" if language == "zh" else "I identified this as an order-support request, but I did not find a matching QuickBooks invoice or sales receipt yet. Please confirm the order number, invoice number, or customer name."
        return _status_update(message, "lookup_order")

    entity = match.get("entity", "Transaction")
    doc_number = match.get("doc_number", "unknown")
    customer_name = match.get("customer_name") or "unknown customer"
    total_amt = match.get("total_amt")
    balance = match.get("balance")
    txn_date = match.get("txn_date")
    due_date = match.get("due_date")
    ship_date = match.get("ship_date")

    if language == "zh":
        details = [f"类型：{entity}", f"单号：{doc_number}", f"客户：{customer_name}"]
        if txn_date:
            details.append(f"交易日期：{txn_date}")
        if due_date:
            details.append(f"到期日：{due_date}")
        if ship_date:
            details.append(f"发货日期：{ship_date}")
        if total_amt is not None:
            details.append(f"总额：{total_amt}")
        if balance is not None:
            details.append(f"未结金额：{balance}")
        return answer(f"我已经从 QuickBooks 找到相关订单/发票记录。当前最匹配结果为：{'；'.join(details)}。", ["lookup_order"])

    details = [f"type: {entity}", f"number: {doc_number}", f"customer: {customer_name}"]
    if txn_date:
        details.append(f"transaction date: {txn_date}")
    if due_date:
        details.append(f"due date: {due_date}")
    if ship_date:
        details.append(f"ship date: {ship_date}")
    if total_amt is not None:
        details.append(f"total: {total_amt}")
    if balance is not None:
        details.append(f"balance: {balance}")
    return answer(f"I found a matching QuickBooks record. Current best match: {'; '.join(details)}.", ["lookup_order"])


def _render_shipping(block, language: str) -> FinalResponse:
    status = block.payload.get("status", "")
    match = block.payload.get("match") or {}

    if status == "not_configured":
        message = "delivery 查询模块已经接到 QuickBooks，但当前还没有完成配置。请先在 .env 中补齐 QuickBooks 凭证。" if language == "zh" else "The delivery lookup flow is wired to QuickBooks, but the integration is not configured yet. Please complete the QuickBooks credentials in .env first."
        return _status_update(message, "lookup_shipping")
    if status == "not_connected":
        message = "QuickBooks 已配置，但还没有完成授权连接。请先打开 /qb/connect 完成 OAuth 授权，再重新查询 delivery。" if language == "zh" else "QuickBooks is configured but not connected yet. Open /qb/connect to complete OAuth, then retry the delivery lookup."
        return _status_update(message, "lookup_shipping")
    if status == "needs_input":
        message = "我已经进入 delivery 查询流程，但还缺少可用于 QuickBooks 查询的关键信息。请提供订单号、invoice number、客户名称，或目的地。" if language == "zh" else "I reached the delivery lookup flow, but I still need a usable identifier. Please share an order number, invoice number, customer name, or destination."
        missing = ["订单号、invoice number、客户名称，或目的地"] if language == "zh" else ["order number, invoice number, customer name, or destination"]
        return _clarification(message, missing, "lookup_shipping")
    if not match:
        message = "我已经识别到这是 delivery / shipping 相关问题，但当前还没有查到匹配的 QuickBooks 记录。请确认订单号、invoice number、客户名称，或补充更准确的目的地信息。" if language == "zh" else "I identified this as a delivery or shipping request, but I did not find matching QuickBooks data yet. Please confirm the order number, invoice number, customer name, or destination."
        return _status_update(message, "lookup_shipping")

    ship_date = match.get("ship_date")
    ship_city = match.get("ship_city")
    ship_country = match.get("ship_country")
    doc_number = match.get("doc_number", "unknown")
    entity = match.get("entity", "Transaction")
    customer_name = match.get("customer_name")
    destination_text = " ".join(part for part in [ship_city, ship_country] if part)

    if language == "zh":
        details = [f"类型：{entity}", f"单号：{doc_number}"]
        if customer_name:
            details.append(f"客户：{customer_name}")
        if ship_date:
            details.append(f"发货日期：{ship_date}")
        if destination_text:
            details.append(f"目的地：{destination_text}")
        return answer(f"我已经从 QuickBooks 找到相关 delivery 信息。当前最匹配结果为：{'；'.join(details)}。", ["lookup_shipping"])

    details = [f"type: {entity}", f"number: {doc_number}"]
    if customer_name:
        details.append(f"customer: {customer_name}")
    if ship_date:
        details.append(f"ship date: {ship_date}")
    if destination_text:
        details.append(f"destination: {destination_text}")
    return answer(f"I found shipping-related QuickBooks data. Current best match: {'; '.join(details)}.", ["lookup_shipping"])


def render_operational(payload: dict) -> FinalResponse:
    focus = payload["response_resolution"].answer_focus
    language = payload["language"]
    blocks = {block.kind: block for block in payload["content_blocks"]}

    if focus == "customer_profile":
        block = blocks.get("customer_profile")
        if block is None:
            raise InsufficientContentError("Operational renderer requires a customer_profile block.")
        return _render_customer(block, language)
    if focus == "invoice_status":
        block = blocks.get("invoice_status")
        if block is None:
            raise InsufficientContentError("Operational renderer requires an invoice_status block.")
        return _render_invoice(block, language)
    if focus == "order_status":
        block = blocks.get("order_status")
        if block is None:
            raise InsufficientContentError("Operational renderer requires an order_status block.")
        return _render_order(block, language)
    if focus == "shipping_status":
        block = blocks.get("shipping_status")
        if block is None:
            raise InsufficientContentError("Operational renderer requires a shipping_status block.")
        return _render_shipping(block, language)

    raise InsufficientContentError(f"Unsupported operational answer focus: {focus}")
