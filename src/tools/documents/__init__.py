from __future__ import annotations

from src.tools.registry import register_tool

from .capability import DOCUMENT_LOOKUP_CAPABILITY
from .documentation_tool import execute_document_lookup


register_tool(
    tool_name=DOCUMENT_LOOKUP_CAPABILITY.tool_name,
    executor=execute_document_lookup,
    capability=DOCUMENT_LOOKUP_CAPABILITY,
    family="documents",
    description="Structured document metadata and inventory lookup.",
)


__all__ = [
    "DOCUMENT_LOOKUP_CAPABILITY",
    "execute_document_lookup",
]
