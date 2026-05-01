from __future__ import annotations

from src.tools.models import ToolCapability


TECHNICAL_RAG_CAPABILITY = ToolCapability(
    tool_name="technical_rag_tool",
    description="检索技术文档知识库，返回实验方案、使用指南、故障排查等非结构化技术内容",
    supported_object_types=["service", "product", "scientific_target"],
    supported_demands=["technical"],
    supported_dialogue_acts=["inquiry", "selection"],
    supported_modalities=["unstructured_retrieval", "hybrid"],
    supported_request_flags=[
        "needs_protocol", "needs_troubleshooting", "needs_recommendation",
        "needs_regulatory_info",
    ],
    returns_structured_facts=True,
    returns_unstructured_snippets=True,
)
