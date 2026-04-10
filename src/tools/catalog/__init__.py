from __future__ import annotations

from src.tools.registry import register_tool

from .capability import CATALOG_LOOKUP_CAPABILITY, PRICING_LOOKUP_CAPABILITY
from .pricing_tool import execute_pricing_lookup_tool
from .product_tool import execute_catalog_lookup


register_tool(
    tool_name=CATALOG_LOOKUP_CAPABILITY.tool_name,
    executor=execute_catalog_lookup,
    capability=CATALOG_LOOKUP_CAPABILITY,
    family="catalog",
    description="Structured catalog lookup for products and services.",
)

register_tool(
    tool_name=PRICING_LOOKUP_CAPABILITY.tool_name,
    executor=execute_pricing_lookup_tool,
    capability=PRICING_LOOKUP_CAPABILITY,
    family="catalog",
    description="Structured pricing lookup over catalog records.",
)


__all__ = [
    "CATALOG_LOOKUP_CAPABILITY",
    "PRICING_LOOKUP_CAPABILITY",
    "execute_catalog_lookup",
    "execute_pricing_lookup_tool",
]
