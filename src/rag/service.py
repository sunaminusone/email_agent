from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping

from src.rag.query_scope import (
    canonicalize_service_name,
    detect_intent_bucket,
    normalize_scope_query,
    query_has_product_scope_marker,
    query_has_service_scope_marker,
    query_mentions_scope,
    resolve_effective_scope,
)
from src.rag.retriever import retrieve_chunks


_CONTEXT_DEPENDENT_QUERY_PATTERNS = (
    re.compile(r"\bit\b", re.I),
    re.compile(r"\bits\b", re.I),
    re.compile(r"\bthis\b", re.I),
    re.compile(r"\bthat\b", re.I),
    re.compile(r"\bthe service\b", re.I),
    re.compile(r"\bthe platform\b", re.I),
    re.compile(r"\bthe product\b", re.I),
    re.compile(r"\bthe target\b", re.I),
)

_REFERENTIAL_SCOPE_PATTERNS = (
    re.compile(r"\bthis antibody\b", re.I),
    re.compile(r"\bthat antibody\b", re.I),
    re.compile(r"\bthis product\b", re.I),
    re.compile(r"\bthat product\b", re.I),
    re.compile(r"\bthis service\b", re.I),
    re.compile(r"\bthat service\b", re.I),
    re.compile(r"\bthe product\b", re.I),
    re.compile(r"\bthe service\b", re.I),
    re.compile(r"\bit\b", re.I),
)

_MAX_EXPANDED_QUERIES = 4


def _first_value(values: Any) -> str:
    if isinstance(values, list):
        for value in values:
            cleaned = str(value or "").strip()
            if cleaned:
                return cleaned
        return ""
    return str(values or "").strip()


def _dedupe_variants(values: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for value in values:
        normalized = normalize_scope_query(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(str(value).strip())
    return deduped


def _normalize_retrieval_context(
    retrieval_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw_context = dict(retrieval_context or {})
    normalized: dict[str, Any] = {}

    for key in (
        "usage_context",
        "experiment_type",
        "customer_goal",
        "pain_point",
        "requested_action",
        "regulatory_or_compliance_note",
    ):
        value = str(raw_context.get(key) or "").strip()
        if value:
            normalized[key] = value

    keywords = [
        str(item).strip()
        for item in (raw_context.get("keywords") or [])
        if str(item).strip()
    ]
    if keywords:
        normalized["keywords"] = _dedupe_variants(keywords)

    return normalized


def _default_scope_context(
    *,
    query: str,
    active_service_name: str,
    active_product_name: str,
    product_names: List[str],
    service_names: List[str],
) -> dict[str, Any]:
    active_entity_kind = ""
    if active_service_name:
        active_entity_kind = "service"
    elif active_product_name:
        active_entity_kind = "product"

    return {
        "query": query,
        "original_query": query,
        "effective_query": query,
        "context": {
            "semantic_intent": "technical_question",
        },
        "entities": {
            "service_names": list(service_names),
            "product_names": list(product_names),
            "catalog_numbers": [],
        },
        "product_lookup_keys": {
            "service_names": [],
            "product_names": [],
            "catalog_numbers": [],
        },
        "active_service_name": active_service_name,
        "active_product_name": active_product_name,
        "session_payload": {
            "active_service_name": active_service_name,
            "active_product_name": active_product_name,
            "active_entity": {
                "entity_kind": active_entity_kind,
            },
        },
        "routing_memory": {
            "should_stick_to_active_route": bool(active_entity_kind),
            "session_payload": {
                "active_entity": {
                    "entity_kind": active_entity_kind,
                },
            },
        },
        "turn_resolution": {
            "turn_type": "follow_up" if active_entity_kind else "",
        },
    }


def _is_context_dependent_query(query: str) -> bool:
    normalized_query = normalize_scope_query(query)
    if not normalized_query:
        return False
    if any(pattern.search(query) for pattern in _CONTEXT_DEPENDENT_QUERY_PATTERNS):
        return True
    return len(normalized_query.split()) <= 7


def _build_expanded_queries(
    *,
    retrieval_hints: Mapping[str, Any] | None = None,
) -> list[str]:
    retrieval_hints = retrieval_hints or {}
    candidates = list(retrieval_hints.get("expanded_queries", []))
    return _dedupe_variants(candidates)[:_MAX_EXPANDED_QUERIES]


def _rewrite_query(query: str, scope: Mapping[str, str], intent_bucket: str) -> tuple[str, str]:
    scope_name = str(scope.get("name") or "").strip()
    cleaned_query = str(query or "").strip()
    if not cleaned_query or not scope_name:
        return "", "no_rewrite_missing_scope"

    if intent_bucket == "service_plan" and re.fullmatch(r"(?i)what is (?:the |your )?service plan\??", cleaned_query):
        return f"What is the service plan for {scope_name}?", "injected_scope_for_service_plan"

    if intent_bucket == "model_support" and re.fullmatch(r"(?i)what models do you support\??", cleaned_query):
        return f"What models does {scope_name} support?", "injected_scope_for_model_support"

    if re.fullmatch(r"(?i)how does (?:it|this|that) work\??", cleaned_query):
        return f"How does {scope_name} work?", "injected_scope_for_pronoun_workflow_question"

    for pattern in _REFERENTIAL_SCOPE_PATTERNS:
        if pattern.search(cleaned_query):
            rewritten_query = pattern.sub(scope_name, cleaned_query, count=1)
            return rewritten_query, "injected_scope_for_referential_entity"

    suffix_query = cleaned_query.rstrip(" ?")
    if cleaned_query.endswith("?"):
        return f"{suffix_query} for {scope_name}?", "injected_scope_by_suffix"
    return f"{suffix_query} for {scope_name}", "injected_scope_by_suffix"


def build_retrieval_queries(
    *,
    query: str,
    retrieval_hints: Dict[str, Any] | None = None,
    retrieval_context: Mapping[str, Any] | None = None,
    active_service_name: str = "",
    active_product_name: str = "",
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    scope_context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    retrieval_hints = retrieval_hints or {}
    product_names = product_names or []
    service_names = service_names or []

    scope_input = _default_scope_context(
        query=query,
        active_service_name=active_service_name,
        active_product_name=active_product_name,
        product_names=product_names,
        service_names=service_names,
    )
    if scope_context:
        scope_input.update(scope_context)
    effective_scope = resolve_effective_scope(scope_input)

    rewrite_reason = "no_rewrite_no_scope"
    rewritten_query = ""
    intent_bucket = detect_intent_bucket(query)

    if not effective_scope.get("scope_type"):
        rewrite_reason = f"no_rewrite_{effective_scope.get('reason', 'no_scope')}"
    elif query_mentions_scope(query, effective_scope.get("name", "")):
        rewrite_reason = "no_rewrite_query_already_scoped"
    else:
        normalized_query = normalize_scope_query(query)
        scope_type = effective_scope.get("scope_type", "")
        has_matching_marker = (
            query_has_service_scope_marker(query)
            if scope_type == "service"
            else query_has_product_scope_marker(query)
        )
        if _is_context_dependent_query(query) or has_matching_marker:
            rewritten_query, rewrite_reason = _rewrite_query(query, effective_scope, intent_bucket)
        else:
            rewrite_reason = "no_rewrite_query_self_contained"

    expanded_queries = _build_expanded_queries(retrieval_hints=retrieval_hints)

    return {
        "primary_query": str(query or "").strip(),
        "rewritten_query": rewritten_query,
        "expanded_queries": expanded_queries,
        "rewrite_reason": rewrite_reason,
        "intent_bucket": intent_bucket,
        "used_llm_contextualizer": False,
        "effective_scope": effective_scope,
        "retrieval_context": _normalize_retrieval_context(retrieval_context),
    }


def retrieve_technical_knowledge(
    *,
    query: str,
    business_line_hint: str = "",
    retrieval_hints: Dict[str, Any] | None = None,
    retrieval_context: Mapping[str, Any] | None = None,
    active_service_name: str = "",
    active_product_name: str = "",
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    top_k: int = 5,
    scope_context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    retrieval_hints = retrieval_hints or {}
    product_names = product_names or []
    service_names = service_names or []
    active_service_name = canonicalize_service_name(active_service_name)

    query_plan = build_retrieval_queries(
        query=query,
        retrieval_hints=retrieval_hints,
        retrieval_context=retrieval_context,
        active_service_name=active_service_name,
        active_product_name=active_product_name,
        product_names=product_names,
        service_names=service_names,
        scope_context=scope_context,
    )

    result = retrieve_chunks(
        query=query_plan["primary_query"],
        rewritten_query=query_plan["rewritten_query"],
        top_k=top_k,
        business_line_hint=business_line_hint,
        active_service_name=active_service_name,
        active_product_name=active_product_name,
        product_names=product_names,
        service_names=service_names,
        expanded_queries=query_plan["expanded_queries"],
        intent_bucket=query_plan["intent_bucket"],
        retrieval_context=query_plan["retrieval_context"],
    )

    matches = []
    for item in result["matches"]:
        metadata = item["metadata"]
        breakdown = item.get("score_breakdown") or {}
        matches.append(
            {
                "chunk_key": metadata.get("chunk_key", ""),
                "score": round(item["score"], 4),
                "raw_score": round(item["raw_score"], 4),
                "priority_tier": item.get("priority_tier", 5),
                "final_score": round(float(item.get("final_score") or item["score"]), 4),
                "score_breakdown": {
                    k: (round(float(v), 4) if isinstance(v, (int, float)) else v)
                    for k, v in breakdown.items()
                },
                "query_variant": item["query_variant"],
                "chunk_strategy": metadata.get("chunk_strategy", "unknown"),
                "section_type": metadata.get("section_type", ""),
                "structural_tag": metadata.get("structural_tag", ""),
                "chunk_label": metadata.get("chunk_label", ""),
                "source_path": metadata.get("source_path", ""),
                "file_name": metadata.get("file_name", ""),
                "business_line": metadata.get("business_line", "unknown"),
                "document_type": metadata.get("document_type", "technical_text"),
                "content_preview": item["content"][:700],
            }
        )

    effective_scope = query_plan["effective_scope"]

    return {
        "retrieval_mode": result["retrieval_mode"],
        "query": query,
        "query_variants": result["query_variants"],
        "business_line_hint": business_line_hint,
        "documents_found": len(matches),
        "matches": matches,
        "confidence": result.get("confidence", {}),
        "retrieval_debug": {
            "effective_scope_type": effective_scope.get("scope_type", ""),
            "effective_scope_name": effective_scope.get("name", ""),
            "effective_scope_source": effective_scope.get("source", ""),
            "effective_scope_reason": effective_scope.get("reason", ""),
            "rewritten_query": query_plan["rewritten_query"],
            "rewrite_reason": query_plan["rewrite_reason"],
            "intent_bucket": query_plan["intent_bucket"],
            "expanded_queries": query_plan["expanded_queries"],
            "retrieval_context": query_plan["retrieval_context"],
            "used_llm_contextualizer": query_plan["used_llm_contextualizer"],
            "variant_observability": result.get("variant_observability", {}),
        },
    }


__all__ = ["build_retrieval_queries", "retrieve_technical_knowledge"]
