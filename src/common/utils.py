from __future__ import annotations


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
