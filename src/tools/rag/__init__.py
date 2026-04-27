from __future__ import annotations

from src.tools.registry import register_tool

from .capability import TECHNICAL_RAG_CAPABILITY
from .historical_capability import HISTORICAL_THREAD_CAPABILITY
from .historical_thread_tool import execute_historical_thread_lookup
from .technical_tool import execute_technical_rag_lookup


register_tool(
    tool_name=TECHNICAL_RAG_CAPABILITY.tool_name,
    executor=execute_technical_rag_lookup,
    capability=TECHNICAL_RAG_CAPABILITY,
    family="rag",
    description="Technical semantic retrieval over service and product content.",
)

register_tool(
    tool_name=HISTORICAL_THREAD_CAPABILITY.tool_name,
    executor=execute_historical_thread_lookup,
    capability=HISTORICAL_THREAD_CAPABILITY,
    family="rag",
    description="Historical sales-reply retrieval for CSR reference (HubSpot form inquiries).",
)


__all__ = [
    "TECHNICAL_RAG_CAPABILITY",
    "HISTORICAL_THREAD_CAPABILITY",
    "execute_technical_rag_lookup",
    "execute_historical_thread_lookup",
]
