import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.schemas import AgentContext, ExecutionRun, FinalResponse, ResponseResolution, RouteDecision


@dataclass
class ResponseContext:
    agent_input: AgentContext
    route: RouteDecision
    execution_run: ExecutionRun
    response_resolution: ResponseResolution
    action_types: List[str]
    language: str
    query: str


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def format_address_text(address: Dict[str, Any]) -> str:
    return ", ".join(
        part
        for part in [
            address.get("Line1"),
            address.get("City"),
            address.get("CountrySubDivisionCode"),
            address.get("PostalCode"),
            address.get("Country"),
        ]
        if part
    )


def requested_customer_fields(query: str) -> set[str]:
    normalized = normalize_text(query)
    fields = set()

    if any(term in normalized for term in ["email", "e-mail", "mail"]):
        fields.add("email")
    if any(term in normalized for term in ["phone", "telephone", "mobile", "contact number"]):
        fields.add("phone")
    if any(term in normalized for term in ["address", "billing address", "shipping address", "location"]):
        fields.add("address")
    if any(term in normalized for term in ["open balance", "balance", "owed", "owes", "欠款", "余额"]):
        fields.add("open_balance")
    if any(term in normalized for term in ["profile", "details", "info", "information", "资料", "详情", "客户信息"]):
        fields.add("full_profile")

    return fields


def requested_invoice_fields(query: str) -> set[str]:
    normalized = normalize_text(query)
    fields = set()

    if any(term in normalized for term in ["due date", "due", "到期"]):
        fields.add("due_date")
    if any(term in normalized for term in ["billing address", "bill address", "账单地址"]):
        fields.add("billing_address")
    if any(term in normalized for term in ["shipping address", "ship address", "delivery address", "收货地址", "配送地址"]):
        fields.add("shipping_address")
    if any(term in normalized for term in ["address", "location", "地址"]) and "billing_address" not in fields and "shipping_address" not in fields:
        fields.add("address")
    if any(term in normalized for term in ["balance", "open balance", "owed", "unpaid", "余额", "欠款"]):
        fields.add("balance")
    if any(term in normalized for term in ["total", "amount", "price", "总额", "金额"]):
        fields.add("total")
    if any(term in normalized for term in ["status", "email status", "print status", "状态"]):
        fields.add("status")
    if any(term in normalized for term in ["invoice date", "date", "开票日期", "发票日期"]) and "due_date" not in fields:
        fields.add("invoice_date")
    if any(term in normalized for term in ["details", "info", "information", "record", "资料", "详情", "发票信息"]):
        fields.add("full_profile")

    return fields


def requested_order_fields(query: str) -> set[str]:
    normalized = normalize_text(query)
    fields = set()

    if any(term in normalized for term in ["ship date", "shipping date", "delivery date", "发货日期", "配送日期"]):
        fields.add("ship_date")
    if any(term in normalized for term in ["due date", "due", "到期"]):
        fields.add("due_date")
    if any(term in normalized for term in ["status", "state", "状态"]):
        fields.add("status")
    if any(term in normalized for term in ["balance", "open balance", "owed", "unpaid", "余额", "欠款"]):
        fields.add("balance")
    if any(term in normalized for term in ["total", "amount", "price", "总额", "金额"]):
        fields.add("total")
    if any(term in normalized for term in ["date", "transaction date", "invoice date", "交易日期", "日期"]) and "due_date" not in fields and "ship_date" not in fields:
        fields.add("transaction_date")
    if any(term in normalized for term in ["customer", "company", "客户", "公司"]) and "status" not in fields:
        fields.add("customer")
    if any(term in normalized for term in ["details", "info", "information", "record", "资料", "详情", "订单信息"]):
        fields.add("full_profile")

    return fields


def requested_shipping_fields(query: str) -> set[str]:
    normalized = normalize_text(query)
    fields = set()

    if any(term in normalized for term in ["ship date", "shipping date", "delivery date", "发货日期", "配送日期"]):
        fields.add("ship_date")
    if any(term in normalized for term in ["destination", "where", "city", "country", "address", "destination address", "目的地", "地址", "城市", "国家"]):
        fields.add("destination")
    if any(term in normalized for term in ["customer", "company", "客户", "公司"]):
        fields.add("customer")
    if any(term in normalized for term in ["status", "state", "状态"]):
        fields.add("status")
    if any(term in normalized for term in ["details", "info", "information", "record", "资料", "详情", "物流信息", "发货信息"]):
        fields.add("full_profile")

    return fields


class BaseResponder:
    action_type: str = ""

    def find_action(self, ctx: ResponseContext):
        return next(
            (action for action in ctx.execution_run.executed_actions if action.action_type == self.action_type),
            None,
        )

    def answer(self, message: str) -> FinalResponse:
        return FinalResponse(
            message=message,
            response_type="answer",
            grounded_action_types=[self.action_type],
        )

    def status_update(self, message: str, grounded_action_types: Optional[List[str]] = None) -> FinalResponse:
        return FinalResponse(
            message=message,
            response_type="status_update",
            grounded_action_types=grounded_action_types or [self.action_type],
        )

    def clarification(self, message: str, missing_information: List[str]) -> FinalResponse:
        return FinalResponse(
            message=message,
            response_type="clarification",
            missing_information_requested=missing_information,
            grounded_action_types=[self.action_type],
        )
