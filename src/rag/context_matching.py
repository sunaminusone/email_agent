from __future__ import annotations

from typing import Any


_EXPERIMENT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "western blot": ("western blot", "wb"),
    "elisa": ("elisa",),
    "flow cytometry": ("flow cytometry", "fcm"),
    "immunohistochemistry": ("immunohistochemistry", "ihc"),
    "immunocytochemistry": ("immunocytochemistry", "icc"),
}

_USAGE_CONTEXT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "validation assay": ("validation assay", "validation", "assay validation"),
    "troubleshooting": ("troubleshooting", "troubleshoot"),
    "screening": ("screening",),
    "specificity testing": ("specificity testing", "specificity"),
}

_METADATA_PRIORITY_FIELDS: tuple[str, ...] = (
    "section_type",
    "section_title",
    "chunk_label",
    "tags",
    "topic_group",
    "document_type",
)


def normalize_context_text(text: str) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").replace("-", " ").split())


def _expand_aliases(value: str, alias_map: dict[str, tuple[str, ...]]) -> list[str]:
    normalized = normalize_context_text(value)
    if not normalized:
        return []

    expanded = {normalized}
    for canonical, aliases in alias_map.items():
        normalized_canonical = normalize_context_text(canonical)
        normalized_aliases = {normalize_context_text(alias) for alias in aliases}
        if normalized in normalized_aliases or normalized == normalized_canonical:
            expanded.add(normalized_canonical)
            expanded.update(normalized_aliases)
    return sorted(item for item in expanded if item)


def _metadata_field_map(match: dict[str, Any]) -> dict[str, str]:
    metadata = match.get("metadata", {}) or {}
    return {
        field: normalize_context_text(str(metadata.get(field, "") or ""))
        for field in _METADATA_PRIORITY_FIELDS
        if normalize_context_text(str(metadata.get(field, "") or ""))
    }


def _content_text(match: dict[str, Any]) -> str:
    return normalize_context_text(str(match.get("content", "") or ""))


def _match_value(
    *,
    value: str,
    match: dict[str, Any],
    alias_map: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    alias_map = alias_map or {}
    candidates = _expand_aliases(value, alias_map)
    if not candidates:
        return {"matched": False, "source": "", "field": "", "value": ""}

    metadata_map = _metadata_field_map(match)
    for field, field_value in metadata_map.items():
        for candidate in candidates:
            if candidate and candidate in field_value:
                return {
                    "matched": True,
                    "source": "metadata",
                    "field": field,
                    "value": candidate,
                }

    content_value = _content_text(match)
    for candidate in candidates:
        if candidate and candidate in content_value:
            return {
                "matched": True,
                "source": "content",
                "field": "content",
                "value": candidate,
            }

    return {"matched": False, "source": "", "field": "", "value": ""}


def compute_retrieval_context_matches(
    match: dict[str, Any],
    retrieval_context: dict[str, Any] | None,
) -> dict[str, Any]:
    retrieval_context = dict(retrieval_context or {})

    experiment_type = _match_value(
        value=str(retrieval_context.get("experiment_type") or ""),
        match=match,
        alias_map=_EXPERIMENT_SYNONYMS,
    )
    usage_context = _match_value(
        value=str(retrieval_context.get("usage_context") or ""),
        match=match,
        alias_map=_USAGE_CONTEXT_SYNONYMS,
    )
    pain_point = _match_value(
        value=str(retrieval_context.get("pain_point") or ""),
        match=match,
    )
    customer_goal = _match_value(
        value=str(retrieval_context.get("customer_goal") or ""),
        match=match,
    )
    requested_action = _match_value(
        value=str(retrieval_context.get("requested_action") or ""),
        match=match,
    )
    regulatory_note = _match_value(
        value=str(retrieval_context.get("regulatory_or_compliance_note") or ""),
        match=match,
    )

    keyword_matches: list[dict[str, str]] = []
    for keyword in retrieval_context.get("keywords", []) or []:
        matched = _match_value(value=str(keyword), match=match)
        if matched.get("matched"):
            keyword_matches.append(
                {
                    "value": str(keyword).strip(),
                    "source": str(matched.get("source") or ""),
                    "field": str(matched.get("field") or ""),
                }
            )

    return {
        "experiment_type": experiment_type,
        "usage_context": usage_context,
        "pain_point": pain_point,
        "customer_goal": customer_goal,
        "requested_action": requested_action,
        "regulatory_or_compliance_note": regulatory_note,
        "keywords": {
            "matched_count": len(keyword_matches),
            "matches": keyword_matches,
        },
    }


__all__ = [
    "compute_retrieval_context_matches",
    "normalize_context_text",
]
