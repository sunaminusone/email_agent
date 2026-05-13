import re
from typing import Any, Dict, List


def rank_customer_candidates(candidates: List[Dict[str, Any]], customer_name: str, max_results: int) -> List[Dict[str, Any]]:
    normalized_target = normalize_customer_name(customer_name)
    target_tokens = set(customer_name_tokens(customer_name))
    ranked: List[tuple[int, Dict[str, Any]]] = []

    for candidate in candidates:
        score = 0
        names_to_compare = [
            candidate.get("display_name"),
            candidate.get("company_name"),
            candidate.get("fully_qualified_name"),
        ]
        normalized_variants = [normalize_customer_name(name) for name in names_to_compare if name]
        token_variants = [set(customer_name_tokens(name)) for name in names_to_compare if name]

        if normalized_target in normalized_variants:
            score += 100

        for normalized_variant in normalized_variants:
            if normalized_target and normalized_target in normalized_variant:
                score += 40
            if normalized_variant and normalized_variant in normalized_target:
                score += 25

        for tokens in token_variants:
            overlap = len(target_tokens.intersection(tokens))
            if overlap:
                score += overlap * 10

        if score > 0:
            ranked.append((score, candidate))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in ranked[:max_results]]


def dedupe_matches(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for match in matches:
        key = (match.get("entity"), match.get("id"), match.get("doc_number"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
    return deduped


def normalize_customer_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def customer_name_tokens(value: str) -> List[str]:
    normalized = normalize_customer_name(value)
    return [token for token in normalized.split() if token]
