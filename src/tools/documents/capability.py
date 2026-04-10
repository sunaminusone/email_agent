from __future__ import annotations

from src.tools.models import ToolCapability


DOCUMENT_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="document_lookup_tool",
    supported_object_types=["document", "product", "service"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "ELABORATE"],
    supported_modalities=["structured_lookup", "unstructured_retrieval", "hybrid"],
    can_run_in_parallel=True,
    returns_structured_facts=True,
    returns_unstructured_snippets=True,
)
