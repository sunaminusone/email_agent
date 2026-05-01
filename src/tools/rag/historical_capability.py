from __future__ import annotations

from src.tools.models import ToolCapability


HISTORICAL_THREAD_CAPABILITY = ToolCapability(
    tool_name="historical_thread_tool",
    description="检索过往 HubSpot 表单咨询及销售回复，给客服参考往例如何回复类似询盘",
    supported_object_types=["service", "product", "scientific_target"],
    supported_demands=["technical", "commercial", "operational", "general"],
    supported_dialogue_acts=["inquiry", "selection", "follow_up", "closing"],
    supported_modalities=["unstructured_retrieval"],
    supported_request_flags=[
        "needs_protocol", "needs_troubleshooting", "needs_recommendation",
        "needs_price", "needs_quote", "needs_timeline",
        "needs_documentation", "needs_customization", "needs_sample",
        "needs_comparison", "needs_availability",
    ],
    returns_structured_facts=True,
    returns_unstructured_snippets=True,
)
