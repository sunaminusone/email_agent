from typing import Any, Dict, List

from src.rag.vectorstore import get_vectorstore


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").replace("-", " ").split())


def _tokenize(text: str) -> List[str]:
    normalized = _normalize_text(text)
    return [token for token in normalized.split() if len(token) >= 2]


def _build_query_variants(
    *,
    query: str,
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    targets: List[str] | None = None,
    expanded_queries: List[str] | None = None,
) -> List[str]:
    variants = [query.strip()]
    variants.extend(product_names or [])
    variants.extend(service_names or [])
    variants.extend(targets or [])
    variants.extend(expanded_queries or [])

    deduped: List[str] = []
    seen = set()
    for variant in variants:
        normalized = _normalize_text(variant)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(variant.strip())
    return deduped


def retrieve_chunks(
    *,
    query: str,
    top_k: int = 5,
    business_line_hint: str = "",
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    targets: List[str] | None = None,
    expanded_queries: List[str] | None = None,
) -> Dict[str, Any]:
    store = get_vectorstore()
    query_variants = _build_query_variants(
        query=query,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
        expanded_queries=expanded_queries,
    )

    raw_matches: List[Dict[str, Any]] = []
    query_tokens = set(_tokenize(query))
    for variant in query_variants[:4]:
        for document, score in store.similarity_search_with_score(variant, k=max(top_k * 4, 24)):
            metadata = dict(document.metadata)
            adjusted_score = float(score)
            if business_line_hint and business_line_hint not in {"unknown", "cross_line"}:
                if metadata.get("business_line") == business_line_hint:
                    adjusted_score -= 0.12

            label_tokens = set(
                _tokenize(" ".join(
                    [
                        str(metadata.get("chunk_label", "")),
                        str(metadata.get("catalog_no", "")),
                        str(metadata.get("name", "")),
                        str(metadata.get("title", "")),
                    ]
                ))
            )
            token_overlap = len(query_tokens.intersection(label_tokens))
            if token_overlap:
                adjusted_score -= min(token_overlap * 0.06, 0.18)

            if metadata.get("structural_tag") == "product" and any(term in query_tokens for term in {"price", "catalog", "cost", "quote"}):
                adjusted_score -= 0.08

            raw_matches.append(
                {
                    "query_variant": variant,
                    "score": adjusted_score,
                    "raw_score": float(score),
                    "content": document.page_content,
                    "metadata": metadata,
                }
            )

    raw_matches.sort(key=lambda item: item["score"])

    deduped: List[Dict[str, Any]] = []
    seen_keys = set()
    for match in raw_matches:
        metadata = match["metadata"]
        key = metadata.get("chunk_key") or (
            metadata.get("source_path", ""),
            metadata.get("structural_tag", ""),
            metadata.get("chunk_label", ""),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(match)
        if len(deduped) >= top_k:
            break

    return {
        "retrieval_mode": "chroma_similarity",
        "query": query,
        "query_variants": query_variants,
        "business_line_hint": business_line_hint,
        "documents_found": len(deduped),
        "matches": deduped,
    }
