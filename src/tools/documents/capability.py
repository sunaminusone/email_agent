from __future__ import annotations

from src.tools.models import ToolCapability


DOCUMENT_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="document_lookup_tool",
    description="查询文档管理系统，返回数据表、使用手册、技术文档等文件引用",
    supported_object_types=["document", "product", "service"],
    supported_demands=["technical"],
    supported_dialogue_acts=["inquiry", "selection"],
    supported_modalities=["structured_lookup", "unstructured_retrieval", "hybrid"],
    supported_request_flags=["needs_documentation"],
    required_params=[],
    can_run_in_parallel=True,
    returns_structured_facts=True,
    returns_unstructured_snippets=True,
)
