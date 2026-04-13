from __future__ import annotations

from typing import Any

from src.memory.models import StatefulAnchors


def _read(source: Any, key: str, default=None):
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def extract_active_route_anchor(prior_state: Any | None) -> str:
    thread_state = _read(prior_state, "thread_memory", {})
    return str(_read(thread_state, "active_route", "") or "").strip()


def extract_pending_clarification_anchors(
    prior_state: Any | None,
) -> tuple[str, list[str], str]:
    clarification = _read(prior_state, "clarification_memory", {})
    if clarification is None:
        return "", [], ""
    raw_options = _read(clarification, "pending_candidate_options", []) or []
    return (
        str(_read(clarification, "pending_clarification_type", "") or "").strip(),
        [str(option).strip() for option in raw_options if str(option).strip()],
        str(_read(clarification, "pending_identifier", "") or "").strip(),
    )


def extract_stateful_anchors(prior_state: Any | None = None) -> StatefulAnchors:
    pending_field, pending_options, pending_identifier = extract_pending_clarification_anchors(prior_state)

    return StatefulAnchors(
        active_route=extract_active_route_anchor(prior_state),
        pending_clarification_field=pending_field,
        pending_candidate_options=pending_options,
        pending_identifier=pending_identifier,
    )
