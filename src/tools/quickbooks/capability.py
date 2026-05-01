from __future__ import annotations

from src.tools.models import ToolCapability


CUSTOMER_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="customer_lookup_tool",
    description="查询 QuickBooks 客户信息，返回客户名称、联系方式、历史交易摘要",
    supported_object_types=["customer"],
    supported_demands=["operational"],
    supported_dialogue_acts=["inquiry", "selection"],
    supported_modalities=["external_api"],
    supported_request_flags=[],
    full_identifiers=["customer_identifier"],
    degraded_identifiers=[],
    provides_params=["customer_name", "customer_identifier", "email"],
    returns_structured_facts=True,
)


INVOICE_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="invoice_lookup_tool",
    description="查询 QuickBooks 发票信息，返回发票金额、状态、明细行项目",
    supported_object_types=["invoice", "order", "customer"],
    supported_demands=["operational"],
    supported_dialogue_acts=["inquiry", "selection"],
    supported_modalities=["external_api"],
    supported_request_flags=["needs_invoice"],
    full_identifiers=["invoice_number"],
    degraded_identifiers=["order_number", "customer_name"],
    provides_params=["invoice_number", "order_number", "customer_name"],
    returns_structured_facts=True,
)


ORDER_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="order_lookup_tool",
    description="查询 QuickBooks 订单状态，返回订单详情、付款状态、预计交付时间",
    supported_object_types=["order", "customer"],
    supported_demands=["operational"],
    supported_dialogue_acts=["inquiry", "selection"],
    supported_modalities=["external_api"],
    supported_request_flags=["needs_order_status", "needs_timeline"],
    full_identifiers=["order_number"],
    degraded_identifiers=["customer_name", "customer_identifier"],
    provides_params=["order_number", "customer_name", "invoice_number"],
    returns_structured_facts=True,
)


SHIPPING_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="shipping_lookup_tool",
    description="查询物流配送信息，返回快递单号、配送状态、预计送达时间",
    supported_object_types=["shipment", "order", "customer"],
    supported_demands=["operational"],
    supported_dialogue_acts=["inquiry", "selection"],
    supported_modalities=["external_api"],
    supported_request_flags=["needs_shipping_info"],
    full_identifiers=["tracking_number"],
    degraded_identifiers=["order_number", "customer_name"],
    provides_params=["tracking_number", "order_number", "customer_name"],
    can_run_in_parallel=True,
    returns_structured_facts=True,
)
