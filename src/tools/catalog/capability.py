from __future__ import annotations

from src.tools.models import ToolCapability


CATALOG_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="catalog_lookup_tool",
    supported_object_types=["product", "service"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "ELABORATE"],
    supported_modalities=["structured_lookup", "hybrid"],
    returns_structured_facts=True,
)


PRICING_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="pricing_lookup_tool",
    supported_object_types=["product", "service"],
    supported_dialogue_acts=["INQUIRY", "SELECTION"],
    supported_modalities=["structured_lookup", "hybrid"],
    returns_structured_facts=True,
)
