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


def format_scope_acknowledgement(
    *,
    scope_type: str,
    scope_name: str,
    scope_source: str = "",
    catalog_no: str = "",
    acknowledgement_mode: str = "none",
    language: str = "en",
) -> str:
    scope_type = str(scope_type or "").strip()
    scope_name = str(scope_name or "").strip()
    catalog_no = str(catalog_no or "").strip()
    acknowledgement_mode = str(acknowledgement_mode or "none").strip()

    if not scope_type or not scope_name or acknowledgement_mode == "none":
        return ""

    if scope_type == "product":
        label = format_product_label(scope_name, catalog_no, language=language) if catalog_no else scope_name
        if language == "zh":
            if acknowledgement_mode == "assumed":
                return f"如果你指的是我们刚才讨论的产品 {label}，下面是相关信息。"
            return f"关于你提到的产品 {label}，下面是相关信息。"
        if acknowledgement_mode == "assumed":
            return f"Assuming you mean the previously discussed product, {label}, here is the relevant information."
        return f"Regarding the product you mentioned, {label}, here is the relevant information."

    if scope_type == "service":
        if language == "zh":
            if acknowledgement_mode == "assumed":
                return f"如果你指的是我们刚才讨论的服务 {scope_name}，下面是相关信息。"
            return f"关于你提到的服务 {scope_name}，下面是相关信息。"
        if acknowledgement_mode == "assumed":
            return f"Assuming you mean the previously discussed service, {scope_name}, here is the relevant information."
        return f"Regarding the service you mentioned, {scope_name}, here is the relevant information."

    return ""


def join_sentences(parts: Iterable[str]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())
