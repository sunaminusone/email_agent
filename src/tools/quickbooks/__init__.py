from __future__ import annotations

from src.tools.registry import register_tool

from .capability import (
    CUSTOMER_LOOKUP_CAPABILITY,
    INVOICE_LOOKUP_CAPABILITY,
    ORDER_LOOKUP_CAPABILITY,
    SHIPPING_LOOKUP_CAPABILITY,
)
from .customer_tool import execute_customer_lookup_tool
from .invoice_tool import execute_invoice_lookup_tool
from .order_tool import execute_order_lookup_tool
from .shipping_tool import execute_shipping_lookup_tool


register_tool(
    tool_name=CUSTOMER_LOOKUP_CAPABILITY.tool_name,
    executor=execute_customer_lookup_tool,
    capability=CUSTOMER_LOOKUP_CAPABILITY,
    family="quickbooks",
    description="QuickBooks customer lookup.",
)

register_tool(
    tool_name=INVOICE_LOOKUP_CAPABILITY.tool_name,
    executor=execute_invoice_lookup_tool,
    capability=INVOICE_LOOKUP_CAPABILITY,
    family="quickbooks",
    description="QuickBooks invoice lookup.",
)

register_tool(
    tool_name=ORDER_LOOKUP_CAPABILITY.tool_name,
    executor=execute_order_lookup_tool,
    capability=ORDER_LOOKUP_CAPABILITY,
    family="quickbooks",
    description="QuickBooks order lookup.",
)

register_tool(
    tool_name=SHIPPING_LOOKUP_CAPABILITY.tool_name,
    executor=execute_shipping_lookup_tool,
    capability=SHIPPING_LOOKUP_CAPABILITY,
    family="quickbooks",
    description="QuickBooks shipping lookup.",
)


__all__ = [
    "CUSTOMER_LOOKUP_CAPABILITY",
    "INVOICE_LOOKUP_CAPABILITY",
    "ORDER_LOOKUP_CAPABILITY",
    "SHIPPING_LOOKUP_CAPABILITY",
    "execute_customer_lookup_tool",
    "execute_invoice_lookup_tool",
    "execute_order_lookup_tool",
    "execute_shipping_lookup_tool",
]
