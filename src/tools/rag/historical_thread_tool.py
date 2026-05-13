"""Tool wrapper around the historical-threads retrieval module."""
from __future__ import annotations

from src.tools.models import ToolRequest, ToolResult
from src.tools.result_builders import empty_result, error_result, ok_result


def execute_historical_thread_lookup(request: ToolRequest) -> ToolResult:
    query = (request.query or "").strip()
    if not query:
        return empty_result(
            tool_name=request.tool_name,
            structured_facts={"query": "", "threads": [], "matches": []},
        )

    try:
        from src.rag.historical_threads import retrieve_historical_threads

        output = retrieve_historical_threads(query=query, top_k=8, thread_limit=3)
    except Exception as exc:
        return error_result(
            tool_name=request.tool_name,
            error=f"Historical-thread retrieval failed: {exc}",
            debug_info={"query": query},
        )

    matches = output.get("matches", [])
    threads = output.get("threads", [])

    facts = {
        "query": query,
        "matches_found": len(matches),
        "threads_returned": len(threads),
        "matches": matches,
        "threads": threads,
    }

    if not threads:
        return empty_result(
            tool_name=request.tool_name,
            structured_facts=facts,
        )

    return ok_result(
        tool_name=request.tool_name,
        primary_records=threads,
        structured_facts=facts,
        unstructured_snippets=[_thread_snippet(t) for t in threads],
    )


def _thread_snippet(thread: dict) -> dict[str, object]:
    units = thread.get("units", [])
    first = units[0] if units else {}
    return {
        "source_type": "historical_thread",
        "title": (
            first.get("reply_subject")
            or f"Thread {thread.get('submission_id', '')[:32]}"
        ),
        "content": first.get("page_content", ""),
        "submission_id": thread.get("submission_id", ""),
        "reply_count": thread.get("reply_count", 0),
        "best_score": thread.get("best_score", 0.0),
        "institution": first.get("institution", ""),
        "service_of_interest": first.get("service_of_interest", ""),
    }
