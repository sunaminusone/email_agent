from __future__ import annotations

from src.tools.models import ToolCapability


TECHNICAL_RAG_CAPABILITY = ToolCapability(
    tool_name="technical_rag_tool",
    supported_object_types=["service", "product", "scientific_target"],
    supported_dialogue_acts=["INQUIRY", "ELABORATE", "SELECTION"],
    supported_modalities=["unstructured_retrieval", "hybrid"],
    returns_structured_facts=True,
    returns_unstructured_snippets=True,
)
