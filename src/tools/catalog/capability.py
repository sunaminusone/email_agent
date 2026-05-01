from __future__ import annotations

from src.tools.models import ToolCapability


CATALOG_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="catalog_lookup_tool",
    description="查询产品目录，返回产品规格、型号、应用场景、存储条件等结构化信息",
    supported_object_types=["product", "service"],
    supported_demands=["commercial"],
    supported_dialogue_acts=["inquiry", "selection"],
    supported_modalities=["structured_lookup", "hybrid"],
    supported_request_flags=["needs_availability", "needs_comparison", "needs_sample"],
    provides_params=["catalog_number", "product_name", "business_line"],
    returns_structured_facts=True,
)


PRICING_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="pricing_lookup_tool",
    description="查询产品定价信息，返回单价、批量折扣、报价有效期等",
    supported_object_types=["product", "service"],
    supported_demands=["commercial"],
    supported_dialogue_acts=["inquiry", "selection"],
    supported_modalities=["structured_lookup", "hybrid"],
    supported_request_flags=["needs_price", "needs_quote"],
    returns_structured_facts=True,
)
