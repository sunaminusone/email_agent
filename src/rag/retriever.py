import re
from typing import Any, Dict, List, Set

from src.rag.reranker import rerank_matches
from src.rag.service_page_ingestion import load_service_page_documents
from src.rag.vectorstore import get_vectorstore


_SECTION_TYPE_BOOSTS: Dict[str, Dict[str, float]] = {
    "service_plan": {
        "service_plan": 0.08,
        "plan_summary": 0.08,
        "service_phase": 0.04,
        "timeline_overview": 0.04,
    },
    "workflow": {
        "workflow_overview": 0.08,
        "workflow_step": 0.06,
        "workflow_highlights": 0.05,
    },
    "model_support": {
        "model_support": 0.08,
        "development_capabilities": 0.04,
        "development_capability_overview": 0.04,
    },
}

_TIER_EXACT_PHASE = 0
_TIER_LOGICAL_JUMP_TARGET = 1
_TIER_LOGICAL_JUMP_ANCHOR = 2
_TIER_SUPPLEMENTARY_PHASE = 3
_TIER_PLAN_COMPARISON = 4
_TIER_DEFAULT = 5

_ACTIVE_SERVICE_BOOST: float = 0.15
_EXPLICIT_TERM_EXACT_BOOST: float = 0.20
_EXPLICIT_TERM_ONLY_BOOST: float = 0.10


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").replace("-", " ").split())


def _tokenize(text: str) -> List[str]:
    normalized = _normalize_text(text)
    return [token for token in normalized.split() if len(token) >= 2]


def _normalize_phase_label(raw_value: str) -> str:
    cleaned = raw_value.strip().upper().replace(" ", "")
    cleaned = cleaned.replace("PHASE", "")
    if not cleaned:
        return ""
    if "-" in cleaned:
        prefix, suffix = cleaned.split("-", 1)
        return f"Phase {prefix}-{suffix}"
    roman_numerals = ["VIII", "VII", "VI", "IV", "III", "II", "IX", "X", "V", "I"]
    for numeral in roman_numerals:
        if cleaned == numeral:
            return f"Phase {numeral}"
        if cleaned.startswith(numeral) and len(cleaned) == len(numeral) + 1:
            suffix = cleaned[len(numeral):]
            if suffix.isalpha():
                return f"Phase {numeral}-{suffix}"
    return f"Phase {cleaned}"


def _extract_phase_refs(query: str) -> Set[str]:
    refs: Set[str] = set()
    normalized = query.upper()
    for match in re.finditer(r"\bPHASE\s+(IV|III|II|I|V|VI|VII|VIII|IX|X)(?:[\s-]?([A-Z]))?\b", normalized):
        roman = match.group(1)
        suffix = match.group(2)
        refs.add(f"Phase {roman}-{suffix}" if suffix else f"Phase {roman}")
    return refs


def _extract_after_step(query: str) -> str:
    lowered = query.lower()
    patterns = [
        r"\bafter\s+(.+?)(?:\s+in\b|\s+for\b|\?|$)",
        r"\bfollowing\s+(.+?)(?:\s+in\b|\s+for\b|\?|$)",
        r"\bsubsequent\s+to\s+(.+?)(?:\s+in\b|\s+for\b|\?|$)",
        r"\bnext\s+step\s+after\s+(.+?)(?:\s+in\b|\s+for\b|\?|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return match.group(1).strip()
    return ""


def _extract_volume_ref(query: str) -> str:
    normalized = _normalize_text(query)
    volume_patterns = [
        (r"\b1\s*liter\b", "1 liter"),
        (r"\b500\s*(?:ml|milliliter|milliliters)\b", "500 milliliters"),
        (r"\b100\s*(?:ml|milliliter|milliliters)\b", "100 milliliters"),
    ]
    for pattern, label in volume_patterns:
        if re.search(pattern, normalized):
            return label
    return ""


def _is_plan_comparison_query(query: str) -> bool:
    lowered = _normalize_text(query)
    if not lowered:
        return False
    comparison_markers = ("difference", "compare", "comparison", "versus", "vs")
    mentions_both_plans = "plan a" in lowered and "plan b" in lowered
    return mentions_both_plans and any(marker in lowered for marker in comparison_markers)


def _build_query_variants(
    *,
    query: str,
    rewritten_query: str = "",
    active_product_name: str = "",
    active_service_name: str = "",
    active_target: str = "",
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    targets: List[str] | None = None,
    expanded_queries: List[str] | None = None,
) -> List[str]:
    variants = [query.strip()]
    if rewritten_query:
        variants.append(rewritten_query.strip())
    variants.extend([active_product_name, active_service_name, active_target])
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


def _match_key(metadata: Dict[str, Any]) -> Any:
    return metadata.get("chunk_key") or (
        metadata.get("source_path", ""),
        metadata.get("structural_tag", ""),
        metadata.get("chunk_label", ""),
    )


def _service_label(metadata: Dict[str, Any]) -> str:
    return str(
        metadata.get("parent_service")
        or metadata.get("service_name")
        or metadata.get("page_title")
        or ""
    ).strip()


def _mark_logical_jump_targets(
    matches: List[Dict[str, Any]],
    current_step: str,
    next_step: str,
) -> List[Dict[str, Any]]:
    if not (current_step and next_step and next_step.lower() != "none"):
        return matches

    result = []
    target_found = False
    anchor_found = False

    for i, match in enumerate(matches):
        copied = dict(match)
        metadata = match.get("metadata", {})
        section_type = str(metadata.get("section_type", "") or "").strip()

        if not target_found and section_type == "workflow_step":
            step_name = str(metadata.get("step_name", "") or metadata.get("workflow_step_name", "") or "").strip()
            if step_name == next_step:
                copied["logical_jump_target"] = True
                target_found = True

        if not anchor_found and section_type == "workflow_step":
            step_name = str(metadata.get("step_name", "") or metadata.get("workflow_step_name", "") or "").strip()
            if step_name == current_step:
                copied["logical_jump_anchor"] = True
                anchor_found = True

        result.append(copied)

    return result


def _compute_priority_tier(
    match: Dict[str, Any],
    *,
    phase_refs: Set[str],
    is_plan_comparison: bool,
) -> int:
    metadata = match.get("metadata", {})

    if match.get("query_variant") == "exact_phase_priority":
        return _TIER_EXACT_PHASE

    if match.get("logical_jump_target"):
        return _TIER_LOGICAL_JUMP_TARGET

    if match.get("logical_jump_anchor"):
        return _TIER_LOGICAL_JUMP_ANCHOR

    section_type = str(metadata.get("section_type", "") or "").strip()

    if phase_refs and section_type == "service_phase":
        phase_name = _normalize_phase_label(str(metadata.get("phase_name", "") or ""))
        if phase_name in phase_refs:
            return _TIER_SUPPLEMENTARY_PHASE

    if is_plan_comparison and section_type == "plan_comparison":
        return _TIER_PLAN_COMPARISON

    return _TIER_DEFAULT


def _compute_soft_score(
    match: Dict[str, Any],
    *,
    intent_bucket: str,
    active_service_name: str,
    query: str,
) -> tuple[float, dict]:
    metadata = match.get("metadata", {})

    base = float(match.get("rerank_score", 0.0))

    boosts = _SECTION_TYPE_BOOSTS.get(str(intent_bucket or "").strip(), {})
    section_type = str(metadata.get("section_type", "") or "").strip()
    section_type_boost = float(boosts.get(section_type, 0.0))

    normalized_active = _normalize_text(active_service_name)
    active_service_boost = 0.0
    if normalized_active and _normalize_text(_service_label(metadata)) == normalized_active:
        active_service_boost = _ACTIVE_SERVICE_BOOST

    normalized_query = _normalize_text(query)
    explicit_terms = [t for t in ("purification", "production") if t in normalized_query]
    explicit_term_boost = 0.0

    if len(explicit_terms) == 1:
        target_term = explicit_terms[0]
        competing_term = "production" if target_term == "purification" else "purification"
        volume_ref = _extract_volume_ref(query)
        text = _explicit_match_text(match)
        has_target = target_term in text
        has_competing = competing_term in text
        has_volume = bool(volume_ref and volume_ref in text)

        if has_target and has_volume:
            explicit_term_boost = _EXPLICIT_TERM_EXACT_BOOST
        elif has_target and not has_competing:
            explicit_term_boost = _EXPLICIT_TERM_ONLY_BOOST

    final_score = base + section_type_boost + active_service_boost + explicit_term_boost
    score_breakdown = {
        "base": base,
        "section_type_boost": section_type_boost,
        "active_service_boost": active_service_boost,
        "explicit_term_boost": explicit_term_boost,
    }
    return final_score, score_breakdown


def _best_service_match(query: str) -> tuple[str, int]:
    query_normalized = _normalize_text(query)
    query_tokens = set(_tokenize(query))
    best_label = ""
    best_score = 0
    seen = set()

    for document in load_service_page_documents():
        metadata = dict(document.metadata)
        label = _service_label(metadata)
        if not label or label in seen:
            continue
        seen.add(label)
        label_normalized = _normalize_text(label)
        score = len(query_tokens.intersection(set(_tokenize(label))))
        if label_normalized and label_normalized in query_normalized:
            score += 100
        if score > best_score:
            best_label = label
            best_score = score

    return best_label, best_score


def _match_text(match: Dict[str, Any]) -> str:
    metadata = match.get("metadata", {})
    fields = [
        str(metadata.get("section_title", "") or ""),
        str(metadata.get("chunk_label", "") or ""),
        str(metadata.get("tags", "") or ""),
        str(match.get("content", "") or ""),
    ]
    return _normalize_text(" ".join(fields))


def _explicit_match_text(match: Dict[str, Any]) -> str:
    metadata = match.get("metadata", {})
    fields = [
        str(metadata.get("section_title", "") or ""),
        str(metadata.get("chunk_label", "") or ""),
        str(metadata.get("tags", "") or ""),
    ]
    return _normalize_text(" ".join(fields))


def _explicit_term_priority_matches(
    *,
    query: str,
    matches: List[Dict[str, Any]],
    all_candidates: List[Dict[str, Any]],
    business_line_hint: str,
    active_service_name: str,
) -> List[Dict[str, Any]]:
    normalized_query = _normalize_text(query)
    explicit_terms = [term for term in ("purification", "production") if term in normalized_query]
    if len(explicit_terms) != 1:
        return []

    target_term = explicit_terms[0]
    competing_term = "production" if target_term == "purification" else "purification"
    volume_ref = _extract_volume_ref(query)
    active_service_normalized = _normalize_text(active_service_name)

    preferred: List[Dict[str, Any]] = []

    def _collect_from_pool(pool: List[Dict[str, Any]]) -> None:
        for match in pool:
            metadata = match.get("metadata", {})
            if business_line_hint and business_line_hint not in {"unknown", "cross_line"}:
                if metadata.get("business_line") != business_line_hint:
                    continue
            if active_service_normalized and _normalize_text(_service_label(metadata)) != active_service_normalized:
                continue
            text = _explicit_match_text(match)
            if target_term not in text or competing_term in text:
                continue
            if volume_ref and volume_ref not in text:
                continue
            preferred.append(match)

    _collect_from_pool(matches)
    _collect_from_pool(all_candidates)

    if preferred:
        return preferred

    for document in load_service_page_documents():
        metadata = dict(document.metadata)
        if business_line_hint and business_line_hint not in {"unknown", "cross_line"}:
            if metadata.get("business_line") != business_line_hint:
                continue
        if active_service_normalized and _normalize_text(_service_label(metadata)) != active_service_normalized:
            continue
        synthesized = {
            "query_variant": "explicit_term_fallback",
            "score": -1.0,
            "raw_score": 999.0,
            "content": document.page_content,
            "metadata": metadata,
        }
        text = _explicit_match_text(synthesized)
        if target_term not in text or competing_term in text:
            continue
        if volume_ref and volume_ref not in text:
            continue
        preferred.append(synthesized)

    return preferred


def _phase_priority(metadata: Dict[str, Any], phase_refs: Set[str]) -> int:
    role = str(metadata.get("phase_role", "") or "").strip()
    exact_branch_query = any("-" in ref for ref in phase_refs)
    if exact_branch_query:
        if role == "optional_branch":
            return 0
        if role == "main_phase":
            return 1
        if role == "optional_main_phase":
            return 2
        return 1
    if role == "main_phase":
        return 0
    if role == "optional_main_phase":
        return 1
    if role == "optional_branch":
        return 2
    return 0


def _exact_phase_priority_matches(
    *,
    query: str,
    phase_refs: Set[str],
    business_line_hint: str,
) -> List[Dict[str, Any]]:
    if not phase_refs:
        return []

    best_service_label, best_service_score = _best_service_match(query)
    exact_matches: List[Dict[str, Any]] = []

    for document in load_service_page_documents():
        metadata = dict(document.metadata)
        if metadata.get("section_type") != "service_phase":
            continue
        if business_line_hint and business_line_hint not in {"unknown", "cross_line"}:
            if metadata.get("business_line") != business_line_hint:
                continue
        phase_name = _normalize_phase_label(str(metadata.get("phase_name", "") or ""))
        if phase_name not in phase_refs:
            continue
        exact_matches.append(
            {
                "query_variant": "exact_phase_priority",
                "score": -1.0,
                "raw_score": 999.0,
                "content": document.page_content,
                "metadata": metadata,
            }
        )

    if best_service_label and best_service_score > 0:
        service_scoped = [
            match
            for match in exact_matches
            if _service_label(match.get("metadata", {})) == best_service_label
        ]
        if service_scoped:
            exact_matches = service_scoped

    exact_matches.sort(
        key=lambda match: (
            _phase_priority(match.get("metadata", {}), phase_refs),
            str(match.get("metadata", {}).get("plan_name", "") or ""),
        )
    )
    return exact_matches


def _resolve_jump_target(matches: List[Dict[str, Any]], after_step: str) -> tuple[str, str]:
    if not after_step:
        return "", ""

    after_tokens = set(_tokenize(after_step))
    best_match: Dict[str, Any] | None = None
    best_overlap = 0

    for match in matches:
        metadata = match.get("metadata", {})
        if str(metadata.get("section_type", "") or "") != "workflow_step":
            continue
        step_name = str(metadata.get("step_name", "") or metadata.get("workflow_step_name", "") or "").strip()
        if not step_name:
            continue
        overlap = len(after_tokens.intersection(set(_tokenize(step_name))))
        if not overlap:
            continue
        if best_match is None or overlap > best_overlap or (overlap == best_overlap and float(match.get("score", 0.0)) < float(best_match.get("score", 0.0))):
            best_match = match
            best_overlap = overlap

    if best_match is None:
        return "", ""

    metadata = best_match.get("metadata", {})
    current_step = str(metadata.get("step_name", "") or metadata.get("workflow_step_name", "") or "").strip()
    next_step = str(metadata.get("next_step", "") or "").strip()
    return current_step, next_step


def retrieve_chunks(
    *,
    query: str,
    top_k: int = 5,
    rewritten_query: str = "",
    business_line_hint: str = "",
    active_service_name: str = "",
    active_product_name: str = "",
    active_target: str = "",
    product_names: List[str] | None = None,
    service_names: List[str] | None = None,
    targets: List[str] | None = None,
    expanded_queries: List[str] | None = None,
    intent_bucket: str = "",
) -> Dict[str, Any]:
    store = get_vectorstore()
    query_variants = _build_query_variants(
        query=query,
        rewritten_query=rewritten_query,
        active_product_name=active_product_name,
        active_service_name=active_service_name,
        active_target=active_target,
        product_names=product_names,
        service_names=service_names,
        targets=targets,
        expanded_queries=expanded_queries,
    )

    phase_refs = _extract_phase_refs(query)
    after_step = _extract_after_step(query)

    raw_matches: List[Dict[str, Any]] = []
    search_k = max(top_k * 8, 32)
    if phase_refs:
        search_k = max(search_k, 64)

    for variant in query_variants[:4]:
        for document, score in store.similarity_search_with_score(variant, k=search_k):
            metadata = dict(document.metadata)
            adjusted_score = float(score)
            if business_line_hint and business_line_hint not in {"unknown", "cross_line"}:
                if metadata.get("business_line") == business_line_hint:
                    adjusted_score -= 0.12

            raw_matches.append(
                {
                    "query_variant": variant,
                    "score": adjusted_score,
                    "raw_score": float(score),
                    "content": document.page_content,
                    "metadata": metadata,
                }
            )

    current_step, next_step = _resolve_jump_target(raw_matches, after_step)

    raw_matches.sort(key=lambda item: item["score"])

    deduped: List[Dict[str, Any]] = []
    seen_keys = set()
    candidate_limit = max(top_k * 6, 18)
    if phase_refs:
        candidate_limit = max(candidate_limit, 60)
    for match in raw_matches:
        key = _match_key(match["metadata"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(match)
        if len(deduped) >= candidate_limit:
            break

    reranked = rerank_matches(query, deduped, top_k=max(top_k * 2, 10))

    exact_phase_matches = _exact_phase_priority_matches(
        query=query,
        phase_refs=phase_refs,
        business_line_hint=business_line_hint,
    )
    explicit_fallback = _explicit_term_priority_matches(
        query=query,
        matches=reranked,
        all_candidates=deduped,
        business_line_hint=business_line_hint,
        active_service_name=active_service_name,
    )

    unified_pool: List[Dict[str, Any]] = []
    _unified_seen: set = set()

    def _add_to_pool(candidates: List[Dict[str, Any]]) -> None:
        for m in candidates:
            k = _match_key(m.get("metadata", {}))
            if k not in _unified_seen:
                _unified_seen.add(k)
                unified_pool.append(m)

    _add_to_pool(exact_phase_matches)
    _add_to_pool(explicit_fallback)
    _add_to_pool(reranked)

    is_plan_comparison = _is_plan_comparison_query(query)
    unified_pool = _mark_logical_jump_targets(unified_pool, current_step, next_step)

    for match in unified_pool:
        tier = _compute_priority_tier(
            match, phase_refs=phase_refs, is_plan_comparison=is_plan_comparison
        )
        final_score, breakdown = _compute_soft_score(
            match,
            intent_bucket=intent_bucket,
            active_service_name=active_service_name,
            query=query,
        )
        match["priority_tier"] = tier
        match["final_score"] = final_score
        match["score_breakdown"] = breakdown

    unified_pool.sort(
        key=lambda m: (m["priority_tier"], -m["final_score"], m["score"])
    )

    reranked = unified_pool[:top_k]

    return {
        "retrieval_mode": "chroma_similarity_bge_rerank",
        "query": query,
        "query_variants": query_variants,
        "business_line_hint": business_line_hint,
        "documents_found": len(reranked),
        "matches": reranked,
    }
