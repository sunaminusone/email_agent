from __future__ import annotations

import re
from decimal import Decimal
from typing import Any


DEFAULT_SIMILARITY_THRESHOLD = 0.08
DEFAULT_LIMIT = 10
CATALOG_NUMBER_PATTERNS = [
    re.compile(r"\b\d{5}\b"),
    re.compile(r"\bPM-CAR\d{4}\b", re.IGNORECASE),
    re.compile(r"\bPM-LNP-\d{4}\b", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b", re.IGNORECASE),
]
LOW_SIGNAL_TOKENS = {
    "a",
    "an",
    "and",
    "antibody",
    "are",
    "can",
    "check",
    "do",
    "for",
    "have",
    "i",
    "in",
    "is",
    "of",
    "on",
    "please",
    "price",
    "product",
    "quote",
    "the",
    "to",
    "what",
    "you",
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_query_text(value: str) -> str:
    return clean_text(value).lower()


def like_pattern(value: str) -> str:
    return f"%{value}%"


def token_regex(value: str) -> str:
    escaped = re.escape(value)
    return rf"(^|[^A-Za-z0-9]){escaped}([^A-Za-z0-9]|$)"


def split_query_terms(*values: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_query_text(value)
        for token in re.split(r"[^a-z0-9]+", normalized):
            if len(token) < 2 or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tokens


def extract_catalog_numbers(*values: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned_value = clean_text(value)
        for pattern in CATALOG_NUMBER_PATTERNS:
            for match in pattern.findall(cleaned_value):
                normalized = match.upper()
                if normalized in seen:
                    continue
                seen.add(normalized)
                found.append(normalized)
    return found


def select_search_term(
    query: str,
    product_names: list[str],
    service_names: list[str],
    targets: list[str],
) -> str:
    prioritized_sources = [*product_names, *service_names, *targets, query]
    tokens = split_query_terms(*prioritized_sources)
    meaningful_tokens = [token for token in tokens if token not in LOW_SIGNAL_TOKENS]
    if meaningful_tokens:
        meaningful_tokens.sort(key=lambda token: (not any(ch.isdigit() for ch in token), -len(token), token))
        return meaningful_tokens[0]
    return tokens[0] if tokens else normalize_query_text(query)


def decimal_to_number(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def normalize_business_line_hint(value: str) -> str:
    normalized = normalize_query_text(value)
    if normalized in {"", "unknown", "cross_line"}:
        return ""
    return normalized.replace("_", "-")
