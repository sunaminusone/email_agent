from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping

from src.conversation.context_scope import (
    normalize_scope_query,
    query_has_product_scope_marker,
    query_matches_non_technical_fallback_path,
    query_has_service_scope_marker,
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

_INTENT_EXPANSION_PACKS: dict[str, list[str]] = {
    "service_plan": [
        "discovery services plan",
        "phases",
        "project timeline",
        "workflow summary",
    ],
    "workflow": [
        "workflow",
        "workflow overview",
        "workflow step",
        "next step",
    ],
    "model_support": [
        "supported models",
        "model support",
        "cell types",
        "application models",
    ],
}

_EXPANSION_DENYLIST = (
    "contact",
    "representative",
    "sales rep",
    "support team",
    "customer support",
    "technical support",
    "connect me",
    "put me in touch",
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


def _default_scope_context(
    *,
    query: str,
    active_service_name: str,
    active_product_name: str,
    active_target: str,
    product_names: List[str],
    service_names: List[str],
    targets: List[str],
) -> dict[str, Any]:
    active_entity_kind = ""
    if active_service_name:
        active_entity_kind = "service"
    elif active_product_name:
        active_entity_kind = "product"
    elif active_target:
        active_entity_kind = "scientific_target"

    return {
        "query": query,
        "original_query": query,
        "effective_query": query,
        "context": {
            "primary_intent": "technical_question",
        },
        "entities": {
            "service_names": list(service_names),
            "product_names": list(product_names),
            "catalog_numbers": [],
            "targets": list(targets),
        },
        "product_lookup_keys": {
            "service_names": [],
            "product_names": [],
            "catalog_numbers": [],
            "targets": [],
        },
        "active_service_name": active_service_name,
        "active_product_name": active_product_name,
        "active_target": active_target,
        "session_payload": {
            "active_service_name": active_service_name,
            "active_product_name": active_product_name,
            "active_target": active_target,
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


def _resolve_retrieval_scope(
    *,
    query: str,
    active_service_name: str,
    active_product_name: str,
    active_target: str,
    product_names: List[str],
    service_names: List[str],
    targets: List[str],
    scope_context: Mapping[str, Any] | None,
) -> dict[str, str]:
    scope_input = dict(scope_context or _default_scope_context(
        query=query,
        active_service_name=active_service_name,
        active_product_name=active_product_name,
        active_target=active_target,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
    ))

    resolved_scope = resolve_effective_scope(scope_input)
    if resolved_scope.get("scope_type"):
        return resolved_scope

    if active_service_name and _query_mentions_scope(query, active_service_name):
        return {
            "scope_type": "service",
            "source": "current",
            "name": active_service_name,
            "reason": "query_mentions_active_service_name",
        }
    if active_product_name and _query_mentions_scope(query, active_product_name):
        return {
            "scope_type": "product",
            "source": "current",
            "name": active_product_name,
            "reason": "query_mentions_active_product_name",
        }
    if active_target and _query_mentions_scope(query, active_target):
        return {
            "scope_type": "scientific_target",
            "source": "current",
            "name": active_target,
            "reason": "query_mentions_active_target",
        }

    if active_service_name and not query_matches_non_technical_fallback_path(query):
        service_intent_bucket = _detect_intent_bucket(query, "service")
        if service_intent_bucket in {"service_plan", "model_support", "workflow", "validation"}:
            return {
                "scope_type": "service",
                "source": "active",
                "name": active_service_name,
                "reason": f"active_service_retrieval_fallback_{service_intent_bucket}",
            }

    return resolved_scope


def _query_mentions_scope(query: str, scope_name: str) -> bool:
    normalized_query = normalize_scope_query(query)
    normalized_scope = normalize_scope_query(scope_name)
    return bool(normalized_scope and normalized_scope in normalized_query)


def _is_context_dependent_query(query: str) -> bool:
    normalized_query = normalize_scope_query(query)
    if not normalized_query:
        return False
    if any(pattern.search(query) for pattern in _CONTEXT_DEPENDENT_QUERY_PATTERNS):
        return True
    return len(normalized_query.split()) <= 7


def _detect_intent_bucket(query: str, scope_type: str) -> str:
    normalized_query = normalize_scope_query(query)
    if not normalized_query:
        return "general_technical"

    if scope_type == "service":
        if any(term in normalized_query for term in ("service plan", "plan", "timeline", "phase", "stages")):
            return "service_plan"
        if any(term in normalized_query for term in ("model", "models", "cell types")):
            return "model_support"
        if any(term in normalized_query for term in ("workflow", "next step", "happens next", "what happens next", "process", "after")):
            return "workflow"
        if any(term in normalized_query for term in ("validate", "validation", "assay", "quality evidence")):
            return "validation"
    if scope_type in {"product", "scientific_target"}:
        if any(term in normalized_query for term in ("price", "pricing", "cost", "quote")):
            return "pricing_detail"
        if any(term in normalized_query for term in ("application", "validated", "species", "reactivity", "host")):
            return "product_attributes"

    return "general_technical"


def _is_expansion_eligible(query: str, scope: Mapping[str, str], intent_bucket: str) -> bool:
    normalized_query = normalize_scope_query(query)
    if not normalized_query:
        return False
    if not scope.get("scope_type") or not scope.get("name"):
        return False
    if intent_bucket not in _INTENT_EXPANSION_PACKS:
        return False
    if any(term in normalized_query for term in _EXPANSION_DENYLIST):
        return False
    return True


def _build_expanded_queries(
    *,
    query: str,
    scope: Mapping[str, str],
    intent_bucket: str,
    retrieval_hints: Mapping[str, Any] | None = None,
) -> list[str]:
    retrieval_hints = retrieval_hints or {}
    if not _is_expansion_eligible(query, scope, intent_bucket):
        return _dedupe_variants(list(retrieval_hints.get("expanded_queries", [])))

    scope_name = str(scope.get("name") or "").strip()
    pack = _INTENT_EXPANSION_PACKS.get(intent_bucket, [])

    generated = [f"{scope_name} {term}".strip() for term in pack if term.strip()]
    deduped = _dedupe_variants(generated + list(retrieval_hints.get("expanded_queries", [])))
    return deduped[:_MAX_EXPANDED_QUERIES]


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
    active_service_name: str = "",
    active_product_name: str = "",
    active_target: str = "",
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    targets: List[str] | None = None,
    scope_context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    retrieval_hints = retrieval_hints or {}
    product_names = product_names or []
    service_names = service_names or []
    targets = targets or []

    effective_scope = _resolve_retrieval_scope(
        query=query,
        active_service_name=active_service_name,
        active_product_name=active_product_name,
        active_target=active_target,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
        scope_context=scope_context,
    )

    rewrite_reason = "no_rewrite_no_scope"
    rewritten_query = ""
    intent_bucket = _detect_intent_bucket(query, effective_scope.get("scope_type", ""))

    if not effective_scope.get("scope_type"):
        rewrite_reason = f"no_rewrite_{effective_scope.get('reason', 'no_scope')}"
    elif _query_mentions_scope(query, effective_scope.get("name", "")):
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

    expanded_queries = _build_expanded_queries(
        query=query,
        scope=effective_scope,
        intent_bucket=intent_bucket,
        retrieval_hints=retrieval_hints,
    )

    return {
        "primary_query": str(query or "").strip(),
        "rewritten_query": rewritten_query,
        "expanded_queries": expanded_queries,
        "rewrite_reason": rewrite_reason,
        "intent_bucket": intent_bucket,
        "used_llm_contextualizer": False,
        "effective_scope": effective_scope,
    }


def retrieve_technical_knowledge(
    *,
    query: str,
    business_line_hint: str = "",
    retrieval_hints: Dict[str, Any] | None = None,
    active_service_name: str = "",
    active_product_name: str = "",
    active_target: str = "",
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    targets: List[str] | None = None,
    top_k: int = 5,
    scope_context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    retrieval_hints = retrieval_hints or {}
    product_names = product_names or []
    service_names = service_names or []
    targets = targets or []

    query_plan = build_retrieval_queries(
        query=query,
        retrieval_hints=retrieval_hints,
        active_service_name=active_service_name,
        active_product_name=active_product_name,
        active_target=active_target,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
        scope_context=scope_context,
    )

    result = retrieve_chunks(
        query=query_plan["primary_query"],
        rewritten_query=query_plan["rewritten_query"],
        top_k=top_k,
        business_line_hint=business_line_hint,
        active_service_name=active_service_name,
        active_product_name=active_product_name,
        active_target=active_target,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
        expanded_queries=query_plan["expanded_queries"],
        intent_bucket=query_plan["intent_bucket"],
    )

    matches = []
    boosted_sections: List[Dict[str, Any]] = []
    for item in result["matches"]:
        metadata = item["metadata"]
        section_boost = round(float(item.get("section_boost", 0.0) or 0.0), 4)
        matches.append(
            {
                "score": round(item["score"], 4),
                "raw_score": round(item["raw_score"], 4),
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
        if section_boost > 0:
            boosted_sections.append(
                {
                    "section_type": metadata.get("section_type", ""),
                    "chunk_label": metadata.get("chunk_label", ""),
                    "section_boost": section_boost,
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
        "retrieval_debug": {
            "effective_scope_type": effective_scope.get("scope_type", ""),
            "effective_scope_name": effective_scope.get("name", ""),
            "effective_scope_source": effective_scope.get("source", ""),
            "effective_scope_reason": effective_scope.get("reason", ""),
            "rewritten_query": query_plan["rewritten_query"],
            "rewrite_reason": query_plan["rewrite_reason"],
            "intent_bucket": query_plan["intent_bucket"],
            "expanded_queries": query_plan["expanded_queries"],
            "section_boost_applied": {
                "intent_bucket": query_plan["intent_bucket"],
                "boosted_match_count": len(boosted_sections),
                "boosted_sections": boosted_sections[:3],
            },
            "used_llm_contextualizer": query_plan["used_llm_contextualizer"],
        },
    }


__all__ = ["build_retrieval_queries", "retrieve_technical_knowledge"]
