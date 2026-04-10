from __future__ import annotations

from src.documents.service import lookup_documents
from src.tools.models import ToolRequest, ToolResult
from src.tools.result_builders import empty_result, error_result, ok_result

from .request_mapper import build_document_lookup_params


def execute_document_lookup(request: ToolRequest) -> ToolResult:
    params = build_document_lookup_params(request)
    try:
        output = lookup_documents(**params)
    except Exception as exc:
        return error_result(
            tool_name=request.tool_name,
            error=f"Document lookup failed: {exc}",
            debug_info={"document_params": params},
        )

    matches = output.get("matches", [])
    snippets = [_document_snippet(match) for match in matches]
    facts = {
        "query": request.query,
        "documents_found": output.get("documents_found", len(matches)),
        "matches": matches,
        "document_root": output.get("document_root", ""),
        "catalog_path": output.get("catalog_path", ""),
    }

    if matches:
        return ok_result(
            tool_name=request.tool_name,
            primary_records=matches,
            structured_facts=facts,
            unstructured_snippets=snippets,
            artifacts=_document_artifacts(matches),
            debug_info={"document_params": params},
        )

    return empty_result(
        tool_name=request.tool_name,
        structured_facts=facts,
        debug_info={"document_params": params},
    )


def _document_snippet(match: dict[str, object]) -> dict[str, object]:
    return {
        "source_type": "document",
        "title": match.get("document_name") or match.get("file_name") or "",
        "content": match.get("summary") or match.get("document_type") or "",
        "source_path": match.get("path") or match.get("source_path") or "",
    }


def _document_artifacts(matches: list[dict[str, object]]) -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []
    for match in matches:
        source_path = match.get("path") or match.get("source_path")
        if not source_path:
            continue
        artifacts.append(
            {
                "artifact_type": "document",
                "title": match.get("document_name") or match.get("file_name") or "document",
                "path": source_path,
            }
        )
    return artifacts
