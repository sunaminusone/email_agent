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


def _apply_section_type_boosts(matches: List[Dict[str, Any]], intent_bucket: str) -> List[Dict[str, Any]]:
    boosts = _SECTION_TYPE_BOOSTS.get(str(intent_bucket or "").strip(), {})
    if not boosts:
        return matches

    boosted: List[Dict[str, Any]] = []
    for match in matches:
        metadata = match.get("metadata", {})
        section_type = str(metadata.get("section_type") or "").strip()
        section_boost = float(boosts.get(section_type, 0.0))
        base_rerank_score = float(match.get("rerank_score", -1e9))
        boosted.append(
            {
                **match,
                "section_boost": section_boost,
                "boosted_rerank_score": base_rerank_score + section_boost,
            }
        )

    boosted.sort(
        key=lambda item: (
            -float(item.get("boosted_rerank_score", item.get("rerank_score", -1e9))),
            item["score"],
        )
    )
    return boosted


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


def _prioritize_active_service_matches(matches: List[Dict[str, Any]], active_service_name: str) -> List[Dict[str, Any]]:
    normalized_active = _normalize_text(active_service_name)
    if not normalized_active:
        return matches

    same_service = [
        match for match in matches
        if _normalize_text(_service_label(match.get("metadata", {}))) == normalized_active
    ]
    if not same_service:
        return matches

    other_service = [
        match for match in matches
        if _normalize_text(_service_label(match.get("metadata", {}))) != normalized_active
    ]
    return same_service + other_service


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


def _prioritize_explicit_query_term_matches(query: str, matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_query = _normalize_text(query)
    explicit_terms = [term for term in ("purification", "production") if term in normalized_query]
    if len(explicit_terms) != 1:
        return matches

    target_term = explicit_terms[0]
    competing_term = "production" if target_term == "purification" else "purification"
    volume_ref = _extract_volume_ref(query)

    exact_target: List[Dict[str, Any]] = []
    target_only: List[Dict[str, Any]] = []
    rest: List[Dict[str, Any]] = []

    for match in matches:
        text = _explicit_match_text(match)
        has_target = target_term in text
        has_competing = competing_term in text
        has_volume = bool(volume_ref and volume_ref in text)

        if has_target and has_volume:
            exact_target.append(match)
        elif has_target and not has_competing:
            target_only.append(match)
        else:
            rest.append(match)

    if not exact_target and not target_only:
        return matches
    return exact_target + target_only + rest


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
        if best_match is None or overlap > best_overlap or float(match.get("score", 0.0)) < float(best_match.get("score", 0.0)):
            best_match = match
            best_overlap = overlap

    if best_match is None:
        return "", ""

    metadata = best_match.get("metadata", {})
    current_step = str(metadata.get("step_name", "") or metadata.get("workflow_step_name", "") or "").strip()
    next_step = str(metadata.get("next_step", "") or "").strip()
    return current_step, next_step


def _prepend_priority_matches(
    *,
    query: str,
    matches: List[Dict[str, Any]],
    all_candidates: List[Dict[str, Any]],
    phase_refs: Set[str],
    current_step: str,
    next_step: str,
    business_line_hint: str,
    active_service_name: str,
) -> List[Dict[str, Any]]:
    priority_front: List[Dict[str, Any]] = []
    seen = set()
    is_plan_comparison = _is_plan_comparison_query(query)
    best_service_label = ""
    best_service_score = 0

    if is_plan_comparison:
        best_service_label, best_service_score = _best_service_match(query)
        comparison_matches: List[Dict[str, Any]] = []
        for pool in (matches, all_candidates):
            for match in pool:
                metadata = match.get("metadata", {})
                if str(metadata.get("section_type", "") or "") != "plan_comparison":
                    continue
                comparison_matches.append(match)

        if best_service_label and best_service_score > 0:
            service_scoped = [
                match
                for match in comparison_matches
                if _service_label(match.get("metadata", {})) == best_service_label
            ]
            if service_scoped:
                comparison_matches = service_scoped

        for match in comparison_matches:
            metadata = match.get("metadata", {})
            key = _match_key(metadata)
            if key in seen:
                continue
            seen.add(key)
            priority_front.append(match)

    explicit_term_matches = _explicit_term_priority_matches(
        query=query,
        matches=matches,
        all_candidates=all_candidates,
        business_line_hint=business_line_hint,
        active_service_name=active_service_name,
    )
    for match in explicit_term_matches:
        metadata = match.get("metadata", {})
        key = _match_key(metadata)
        if key in seen:
            continue
        seen.add(key)
        priority_front.append(match)

    if phase_refs:
        best_service_label, best_service_score = _best_service_match(query)
        exact_phase_matches: List[Dict[str, Any]] = []

        def _collect_exact_phase_matches(pool: List[Dict[str, Any]]) -> None:
            for match in pool:
                metadata = match.get("metadata", {})
                if str(metadata.get("section_type", "") or "") != "service_phase":
                    continue
                if business_line_hint and business_line_hint not in {"unknown", "cross_line"}:
                    if metadata.get("business_line") != business_line_hint:
                        continue
                phase_name = _normalize_phase_label(str(metadata.get("phase_name", "") or ""))
                if phase_name not in phase_refs:
                    continue
                exact_phase_matches.append(match)

        _collect_exact_phase_matches(matches)
        _collect_exact_phase_matches(all_candidates)

        # If the current candidate set somehow missed the exact phase chunk, fall back to the
        # full prechunked service-page corpus and synthesize a candidate.
        if not exact_phase_matches:
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
                exact_phase_matches.append(
                    {
                        "query_variant": "exact_phase_fallback",
                        "score": -1.0,
                        "raw_score": 999.0,
                        "content": document.page_content,
                        "metadata": metadata,
                    }
                )

        if best_service_label and best_service_score > 0:
            service_scoped = [
                match
                for match in exact_phase_matches
                if _service_label(match.get("metadata", {})) == best_service_label
            ]
            if service_scoped:
                exact_phase_matches = service_scoped

        exact_phase_matches.sort(
            key=lambda match: (
                _phase_priority(match.get("metadata", {}), phase_refs),
                str(match.get("metadata", {}).get("plan_name", "") or ""),
            )
        )

        for match in exact_phase_matches:
            metadata = match.get("metadata", {})
            key = _match_key(metadata)
            if key in seen:
                continue
            seen.add(key)
            priority_front.append(match)

        for pool in (matches, all_candidates):
            for match in pool:
                metadata = match.get("metadata", {})
                key = _match_key(metadata)
                if key in seen:
                    continue
                if str(metadata.get("section_type", "") or "") != "service_phase":
                    continue
                phase_name = _normalize_phase_label(str(metadata.get("phase_name", "") or ""))
                if phase_name not in phase_refs:
                    continue
                seen.add(key)
                priority_front.append(match)

    if current_step and next_step and next_step.lower() != "none":
        for pool in (matches, all_candidates):
            for match in pool:
                metadata = match.get("metadata", {})
                key = _match_key(metadata)
                if key in seen:
                    continue
                if str(metadata.get("section_type", "") or "") != "workflow_step":
                    continue
                step_name = str(metadata.get("step_name", "") or metadata.get("workflow_step_name", "") or "").strip()
                if step_name == next_step:
                    copied = dict(match)
                    copied["logical_jump_target"] = True
                    seen.add(key)
                    priority_front.append(copied)
                    break
            if priority_front and priority_front[-1].get("logical_jump_target"):
                break

        for pool in (matches, all_candidates):
            for match in pool:
                metadata = match.get("metadata", {})
                key = _match_key(metadata)
                if key in seen:
                    continue
                if str(metadata.get("section_type", "") or "") != "workflow_step":
                    continue
                step_name = str(metadata.get("step_name", "") or metadata.get("workflow_step_name", "") or "").strip()
                if step_name == current_step:
                    copied = dict(match)
                    copied["logical_jump_anchor"] = True
                    seen.add(key)
                    priority_front.append(copied)
                    break
            if priority_front and priority_front[-1].get("logical_jump_anchor"):
                break

    final_matches = list(priority_front)
    ordered_matches = matches
    if is_plan_comparison and best_service_label and best_service_score > 0:
        same_service = [
            match for match in matches if _service_label(match.get("metadata", {})) == best_service_label
        ]
        other_service = [
            match for match in matches if _service_label(match.get("metadata", {})) != best_service_label
        ]
        ordered_matches = same_service + other_service

    for match in ordered_matches:
        key = _match_key(match.get("metadata", {}))
        if key in seen:
            continue
        final_matches.append(match)
    return final_matches


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
    reranked = _apply_section_type_boosts(reranked, intent_bucket)
    reranked = _prioritize_active_service_matches(reranked, active_service_name)
    reranked = _prioritize_explicit_query_term_matches(query, reranked)
    exact_phase_matches = _exact_phase_priority_matches(
        query=query,
        phase_refs=phase_refs,
        business_line_hint=business_line_hint,
    )
    reranked = _prepend_priority_matches(
        query=query,
        matches=reranked,
        all_candidates=deduped,
        phase_refs=set(),
        current_step=current_step,
        next_step=next_step,
        business_line_hint=business_line_hint,
        active_service_name=active_service_name,
    )

    if exact_phase_matches:
        seen_exact = {_match_key(match.get("metadata", {})) for match in exact_phase_matches}
        reranked = exact_phase_matches + [
            match for match in reranked if _match_key(match.get("metadata", {})) not in seen_exact
        ]

    reranked = reranked[:top_k]

    return {
        "retrieval_mode": "chroma_similarity_bge_rerank",
        "query": query,
        "query_variants": query_variants,
        "business_line_hint": business_line_hint,
        "documents_found": len(reranked),
        "matches": reranked,
    }
