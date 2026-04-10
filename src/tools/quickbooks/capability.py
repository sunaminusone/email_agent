from __future__ import annotations

from src.tools.models import ToolCapability


CUSTOMER_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="customer_lookup_tool",
    supported_object_types=["customer"],
    supported_dialogue_acts=["INQUIRY", "SELECTION"],
    supported_modalities=["external_api"],
    returns_structured_facts=True,
    requires_external_system=True,
)


INVOICE_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="invoice_lookup_tool",
    supported_object_types=["invoice", "order", "customer"],
    supported_dialogue_acts=["INQUIRY", "SELECTION"],
    supported_modalities=["external_api"],
    returns_structured_facts=True,
    requires_external_system=True,
)


ORDER_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="order_lookup_tool",
    supported_object_types=["order", "customer"],
    supported_dialogue_acts=["INQUIRY", "SELECTION"],
    supported_modalities=["external_api"],
    returns_structured_facts=True,
    requires_external_system=True,
)


SHIPPING_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="shipping_lookup_tool",
    supported_object_types=["shipment", "order", "customer"],
    supported_dialogue_acts=["INQUIRY", "SELECTION"],
    supported_modalities=["external_api"],
    can_run_in_parallel=True,
    returns_structured_facts=True,
    requires_external_system=True,
)
