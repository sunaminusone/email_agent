from __future__ import annotations

from typing import Iterable


def format_currency(amount: str | int | float | None, currency: str | None = None) -> str:
    if amount in (None, ""):
        return ""
    currency_code = (currency or "USD").upper()
    amount_text = str(amount).strip()
    if amount_text.startswith(("$", "¥", "€")):
        return amount_text
    if currency_code == "USD":
        return f"{amount_text} USD"
    return f"{amount_text} {currency_code}"


def humanize_lead_time(lead_time: str | None, *, language: str = "en", style: str = "concise") -> str:
    if not lead_time:
        return ""
    if language == "zh":
        if style == "sales":
            return f"当前参考交期约为 {lead_time}"
        if style == "customer_friendly":
            return f"目前预计交期为 {lead_time}"
        return f"参考交期为 {lead_time}"
    if style == "sales":
        return f"The current expected lead time is {lead_time}"
    if style == "customer_friendly":
        return f"The expected lead time is {lead_time}"
    return f"The listed lead time is {lead_time}"


def format_product_label(product_name: str, catalog_no: str, *, language: str = "en") -> str:
    if language == "zh":
        return f"{product_name}（编号：{catalog_no}）"
    return f"{product_name} (ID: {catalog_no})"


def format_document_scope(scope: str, *, language: str = "en") -> str:
    if language == "zh":
        return "产品线级资料" if scope == "business_line" else "服务级资料"
    return "product-line" if scope == "business_line" else "service-specific"


def join_sentences(parts: Iterable[str]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())
