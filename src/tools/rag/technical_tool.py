from __future__ import annotations

from src.tools.models import ToolRequest, ToolResult
from src.tools.result_builders import empty_result, error_result, ok_result

from .request_mapper import build_rag_lookup_params


def execute_technical_rag_lookup(request: ToolRequest) -> ToolResult:
    params = build_rag_lookup_params(request)
    try:
        from src.rag.service import retrieve_technical_knowledge

        output = retrieve_technical_knowledge(**params)
    except Exception as exc:
        return error_result(
            tool_name=request.tool_name,
            error=f"Technical retrieval failed: {exc}",
            debug_info={"rag_params": params},
        )

    matches = output.get("matches", [])
    snippets = [_rag_snippet(match) for match in matches]
    facts = {
        "query": request.query,
        "retrieval_mode": output.get("retrieval_mode", ""),
        "documents_found": output.get("documents_found", len(matches)),
        "matches": matches,
        "retrieval_confidence": output.get("confidence", {}),
        "retrieval_debug": output.get("retrieval_debug", {}),
        "query_variants": output.get("query_variants", []),
        "variant_observability": (
            (output.get("retrieval_debug", {}) or {}).get("variant_observability", {})
        ),
    }

    if matches:
        return ok_result(
            tool_name=request.tool_name,
            primary_records=matches,
            structured_facts=facts,
            unstructured_snippets=snippets,
            artifacts=_rag_artifacts(matches),
            debug_info={"rag_params": params},
        )

    return empty_result(
        tool_name=request.tool_name,
        structured_facts=facts,
        debug_info={"rag_params": params},
    )


def _rag_snippet(match: dict[str, object]) -> dict[str, object]:
    return {
        "source_type": "rag_chunk",
        "title": match.get("chunk_label") or match.get("file_name") or "",
        "content": match.get("content_preview") or "",
        "source_path": match.get("source_path") or "",
        "section_type": match.get("section_type") or "",
    }


def _rag_artifacts(matches: list[dict[str, object]]) -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []
    seen: set[str] = set()
    for match in matches:
        source_path = str(match.get("source_path") or "").strip()
        if not source_path or source_path in seen:
            continue
        seen.add(source_path)
        artifacts.append(
            {
                "artifact_type": "source_document",
                "title": match.get("file_name") or source_path.rsplit("/", 1)[-1],
                "path": source_path,
            }
        )
    return artifacts
