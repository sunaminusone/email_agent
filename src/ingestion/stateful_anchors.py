from __future__ import annotations

from typing import Any

from src.ingestion.models import SourceAttribution, StatefulAnchors, ValueSignal


def _read(source: Any, key: str, default=None):
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _to_value_signal(value: str, *, label: str) -> ValueSignal | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    return ValueSignal(
        value=cleaned,
        raw=cleaned,
        normalized_value=cleaned,
        attribution=SourceAttribution(
            source_type="stateful_anchor",
            recency="CONTEXTUAL",
            confidence=1.0,
            source_label=label,
        ),
    )


def extract_active_route_anchor(prior_state: Any | None) -> str:
    thread_state = _read(prior_state, "thread_memory", {})
    return str(_read(thread_state, "active_route", "") or "").strip()


def extract_active_business_line_anchor(prior_state: Any | None) -> ValueSignal | None:
    thread_state = _read(prior_state, "thread_memory", {})
    return _to_value_signal(
        _read(thread_state, "active_business_line", ""),
        label="memory.thread.active_business_line",
    )


def extract_active_entity_anchor(
    prior_state: Any | None,
) -> tuple[ValueSignal | None, ValueSignal | None, ValueSignal | None]:
    object_state = _read(prior_state, "object_memory", {})
    active_object = _read(object_state, "active_object")
    if active_object is None:
        return None, None, None
    return (
        _to_value_signal(_read(active_object, "object_type", ""), label="memory.object.active.kind"),
        _to_value_signal(_read(active_object, "identifier", ""), label="memory.object.active.identifier"),
        _to_value_signal(_read(active_object, "display_name", ""), label="memory.object.active.display_name"),
    )


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
    active_entity_kind, active_entity_identifier, active_entity_display_name = extract_active_entity_anchor(prior_state)
    pending_field, pending_options, pending_identifier = extract_pending_clarification_anchors(prior_state)

    return StatefulAnchors(
        active_route=extract_active_route_anchor(prior_state),
        active_business_line=extract_active_business_line_anchor(prior_state),
        active_entity_kind=active_entity_kind,
        active_entity_identifier=active_entity_identifier,
        active_entity_display_name=active_entity_display_name,
        pending_clarification_field=pending_field,
        pending_candidate_options=pending_options,
        pending_identifier=pending_identifier,
    )
