"""Biotech terminology configuration for RAG retrieval.

Term pairs and volume specs used during scoring / hard-filtering live here
(rather than hard-coded in retriever.py) so that adding a new pair only
requires editing this file — not touching retriever logic.

Phase-1 note: this file carries only the terms that were previously
hard-coded in retriever.py — nothing new has been added. Adding new biotech
term pairs (e.g. expression/purification, upstream/downstream, in_vitro/in_vivo)
is a separate business decision and should be done deliberately.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Tuple


_FUZZY_BIZ_HINTS = {"", "unknown", "cross_line"}


@dataclass(frozen=True)
class MutuallyExclusiveTermPair:
    """A pair of biotech terms where mentioning one implies NOT the other.

    When the user's query contains exactly one side, chunks that include the
    competing side should not receive an explicit-term boost (and in the
    hard-filter path, should be excluded outright).

    `business_lines` empty = globally active. Non-empty = activate only when
    the retrieval's business_line_hint matches one of the listed lines, or
    when the hint is absent/ambiguous.
    """
    terms: Tuple[str, str]
    business_lines: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VolumePattern:
    """A regex + canonical label for biotech volume / scale references."""
    regex: str
    canonical_label: str
    business_lines: Tuple[str, ...] = field(default_factory=tuple)


TERM_PAIRS: tuple[MutuallyExclusiveTermPair, ...] = (
    MutuallyExclusiveTermPair(terms=("purification", "production")),
)


VOLUME_PATTERNS: tuple[VolumePattern, ...] = (
    VolumePattern(regex=r"\b1\s*liter\b", canonical_label="1 liter"),
    VolumePattern(regex=r"\b500\s*(?:ml|milliliter|milliliters)\b", canonical_label="500 milliliters"),
    VolumePattern(regex=r"\b100\s*(?:ml|milliliter|milliliters)\b", canonical_label="100 milliliters"),
)


def _is_active_for_biz(biz_scope: Tuple[str, ...], business_line_hint: str) -> bool:
    if not biz_scope:
        return True
    if business_line_hint in _FUZZY_BIZ_HINTS:
        return True
    return business_line_hint in biz_scope


def find_explicit_terms(
    normalized_query: str,
    business_line_hint: str = "",
) -> tuple[str, str] | None:
    """Return (target, competing) if the query mentions exactly one side of an
    active pair; otherwise None.

    Expects `normalized_query` to already be lowercased / whitespace-normalized
    by the caller (matches retriever.py's `_normalize_text` convention).
    """
    for pair in TERM_PAIRS:
        if not _is_active_for_biz(pair.business_lines, business_line_hint):
            continue
        a, b = pair.terms
        has_a = a in normalized_query
        has_b = b in normalized_query
        if has_a and not has_b:
            return a, b
        if has_b and not has_a:
            return b, a
    return None


def find_volume_ref(
    normalized_query: str,
    business_line_hint: str = "",
) -> str:
    """Return canonical label if the query matches an active volume pattern."""
    for pattern in VOLUME_PATTERNS:
        if not _is_active_for_biz(pattern.business_lines, business_line_hint):
            continue
        if re.search(pattern.regex, normalized_query):
            return pattern.canonical_label
    return ""


__all__ = [
    "MutuallyExclusiveTermPair",
    "VolumePattern",
    "TERM_PAIRS",
    "VOLUME_PATTERNS",
    "find_explicit_terms",
    "find_volume_ref",
]
