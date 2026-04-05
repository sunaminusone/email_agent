from __future__ import annotations

from .common import (
    CONCISE_STYLE_MARKERS,
    CUSTOMER_FRIENDLY_MARKERS,
    TECHNICAL_STYLE_MARKERS,
    has_any,
)


def resolve_reply_style(*, answer_focus: str, query: str) -> str:
    if has_any(query, CUSTOMER_FRIENDLY_MARKERS):
        return "customer_friendly"
    if has_any(query, CONCISE_STYLE_MARKERS):
        return "concise"
    if answer_focus == "technical_context" or has_any(query, TECHNICAL_STYLE_MARKERS):
        return "technical"
    if answer_focus in {"pricing", "lead_time", "documentation"}:
        return "sales"
    return "concise"
