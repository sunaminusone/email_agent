from __future__ import annotations

import re
from typing import Iterable


_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[_\-]+")


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def normalize_text(value: object, *, lowercase: bool = True) -> str:
    text = clean_text(value)
    if not text:
        return ""

    normalized = text.replace("×", "x").replace("&", " and ")
    normalized = _PUNCTUATION_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    normalized = normalized.strip()
    if lowercase:
        normalized = normalized.lower()
    return normalized


def normalize_identifier(value: object) -> str:
    return clean_text(value).upper()


def normalize_object_alias(value: object) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"\b6\s*x?\s*his\b", "6xhis", normalized)
    return normalized


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = clean_text(value)
        normalized = normalize_object_alias(cleaned)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned)

    return deduped
