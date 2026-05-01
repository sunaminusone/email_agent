from __future__ import annotations

from typing import Any


def dedupe_strings(values: list[str]) -> list[str]:
    """Return *values* in original order, stripped and deduplicated."""
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def first_non_empty(*values: Any) -> str:
    """Return the first non-blank stringified value, or "" if all are empty.

    Used by tool request_mappers to pick the best value across primary
    object fields, scope constraints, and resolved object constraints.
    """
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""
