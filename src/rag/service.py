from typing import Any, Dict, List

from src.rag.retriever import retrieve_chunks


def retrieve_technical_knowledge(
    *,
    query: str,
    business_line_hint: str = "",
    retrieval_hints: Dict[str, Any] | None = None,
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    targets: List[str] | None = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    retrieval_hints = retrieval_hints or {}
    result = retrieve_chunks(
        query=query,
        top_k=top_k,
        business_line_hint=business_line_hint,
        product_names=product_names or [],
        service_names=service_names or [],
        targets=targets or [],
        expanded_queries=retrieval_hints.get("expanded_queries", []),
    )

    matches = []
    for item in result["matches"]:
        metadata = item["metadata"]
        matches.append(
            {
                "score": round(item["score"], 4),
                "raw_score": round(item["raw_score"], 4),
                "query_variant": item["query_variant"],
                "chunk_strategy": metadata.get("chunk_strategy", "unknown"),
                "structural_tag": metadata.get("structural_tag", ""),
                "chunk_label": metadata.get("chunk_label", ""),
                "source_path": metadata.get("source_path", ""),
                "file_name": metadata.get("file_name", ""),
                "business_line": metadata.get("business_line", "unknown"),
                "document_type": metadata.get("document_type", "technical_text"),
                "content_preview": item["content"][:700],
            }
        )

    return {
        "retrieval_mode": result["retrieval_mode"],
        "query": query,
        "query_variants": result["query_variants"],
        "business_line_hint": business_line_hint,
        "documents_found": len(matches),
        "matches": matches,
    }
