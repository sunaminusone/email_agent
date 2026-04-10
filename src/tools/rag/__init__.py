from __future__ import annotations

from src.tools.registry import register_tool

from .capability import TECHNICAL_RAG_CAPABILITY
from .technical_tool import execute_technical_rag_lookup


register_tool(
    tool_name=TECHNICAL_RAG_CAPABILITY.tool_name,
    executor=execute_technical_rag_lookup,
    capability=TECHNICAL_RAG_CAPABILITY,
    family="rag",
    description="Technical semantic retrieval over service and product content.",
)


__all__ = [
    "TECHNICAL_RAG_CAPABILITY",
    "execute_technical_rag_lookup",
]
